"""
FastAPI backend with JEV routing.
- complex questions → Groq openai/gpt-oss-120b
- simple questions  → local Ollama llama3.2:3b
"""

import os
from pathlib import Path
from typing import Optional, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from groq import Groq
# from ollama import chat as ollama_chat
from typesafe_sdk import TypeSafeClient, Choice
from ollama import Client

from backend.rag import retrieve_context, build_vectorstore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")

if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY missing")
if not TYPESAFE_API_KEY:
    print("WARNING: TYPESAFE_API_KEY missing")

groq_client = Groq(api_key=GROQ_API_KEY or "missing")

ollama_client = Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))

LARGE_MODEL = "openai/gpt-oss-120b"
SMALL_MODEL = "llama3.2:3b"          # must be pulled in Ollama

SYSTEM_PROMPT = """You are a concise teaching assistant for John C. Hull's "Options, Futures, and Other Derivatives" (8th ed).

Rules:
- Answer using ONLY the provided context.
- Keep the answer short (a few sentences or a short numbered list).
- Use plain text only. No markdown, no bold, no headings, no asterisks.
- If the context is insufficient, say so briefly.
"""

app = FastAPI(title="Hull Derivatives RAG + JEV Router", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    k: Optional[int] = Field(6, ge=1, le=12)


class ChatResponse(BaseModel):
    answer: str
    model: str
    route: Literal["large", "small"]
    context_preview: Optional[str] = None


def decide_route(query: str) -> str:
    """Use JEV to decide large vs small model."""
    try:
        with TypeSafeClient() as client:          # reads TYPESAFE_API_KEY
            response = client.system_one(
                state=query,
                questions={
                    "route": Choice(
                        instructions="Should this question about derivatives be answered by a large powerful model or a small fast local model?",
                        criteria={
                            "large": "Complex reasoning, multi-step calculation, detailed explanation of formulas, proofs, comparisons, or anything that needs deep understanding of the textbook",
                            "small": "Simple definition, short factual recall, basic concept, one-sentence answer, or yes/no style question",
                        },
                    )
                },
            )
        choice = response.choices["route"].choice
        return "large" if choice == "large" else "small"
    except Exception as e:
        print(f"[JEV] routing failed ({e}), defaulting to large")
        return "large"


def call_large(context: str, query: str) -> str:
    user_content = f"""Context from the book:

{context}

---

User question: {query}

Answer based on the context above. Keep it short and plain text only."""

    completion = groq_client.chat.completions.create(
        model=LARGE_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_completion_tokens=1024,
    )
    return completion.choices[0].message.content or "(empty)"


def call_small(context: str, query: str) -> str:
    user_content = f"""Context from the book:

{context}

---

User question: {query}

Answer based on the context above. Keep it short and plain text only."""

    response = ollama_client.chat(
        model=SMALL_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        options={"temperature": 0.3, "num_predict": 512},
    )
    return response["message"]["content"] or "(empty)"


@app.on_event("startup")
def startup():
    print("[startup] Initializing RAG...")
    try:
        build_vectorstore(force_rebuild=False)
        print("[startup] RAG ready.")
    except Exception as e:
        print(f"[startup] WARNING: {e}")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "large_model": LARGE_MODEL,
        "small_model": SMALL_MODEL,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not set")

    # 1. Retrieve context
    try:
        context = retrieve_context(req.query, k=req.k or 6)
    except Exception as e:
        raise HTTPException(500, f"Retrieval failed: {e}")

    # 2. JEV decides the route
    route = decide_route(req.query)
    print(f"[route] '{req.query[:60]}...' → {route}")

    # 3. Call the chosen model
    try:
        if route == "large":
            answer = call_large(context, req.query)
            model_used = LARGE_MODEL
        else:
            answer = call_small(context, req.query)
            model_used = SMALL_MODEL
    except Exception as e:
        raise HTTPException(502, f"LLM call failed ({route}): {e}")

    preview = context[:300] + ("..." if len(context) > 300 else "")

    return ChatResponse(
        answer=answer,
        model=model_used,
        route=route,
        context_preview=preview,
    )


FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)