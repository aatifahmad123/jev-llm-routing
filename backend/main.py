"""
FastAPI backend with JEV routing.
- complex questions → Groq openai/gpt-oss-120b
- simple questions  → local Ollama llama3.2:3b
"""

import os
import time
from pathlib import Path
from typing import Optional, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from groq import Groq
# from ollama import chat as ollama_chat
from typesafe_sdk import TypeSafeClient, Choice
from ollama import Client

from backend.rag import retrieve_context, build_vectorstore
from backend.metrics import metrics
from backend.chat_history import (
    add_message,
    clear_messages,
    conversation_belongs_to_client,
    create_conversation,
    get_messages,
    initialize_database,
    list_conversations,
    set_title_if_new,
)

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
    client_id: str = Field(..., min_length=1, max_length=100)
    conversation_id: Optional[str] = Field(None, min_length=1, max_length=100)


class ChatResponse(BaseModel):
    answer: str
    model: str
    route: Literal["large", "small"]
    context_preview: Optional[str] = None
    conversation_id: str


def decide_route(query: str) -> str:
    """Use JEV to decide large vs small model."""
    try:
        with TypeSafeClient() as client:
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
    initialize_database()
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


@app.get("/dashboard/metrics")
def dashboard_metrics():
    """Return runtime chat and LLM call metrics for the dashboard."""
    return {
        "models": {"large": LARGE_MODEL, "small": SMALL_MODEL},
        **metrics.snapshot(),
    }


@app.get("/conversations")
def conversations(client_id: str = Query(..., min_length=1, max_length=100)):
    return list_conversations(client_id)


@app.post("/conversations")
def new_conversation(client_id: str = Query(..., min_length=1, max_length=100)):
    return create_conversation(client_id)


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, client_id: str):
    if not conversation_belongs_to_client(conversation_id, client_id):
        raise HTTPException(404, "Conversation not found")
    return get_messages(conversation_id, client_id)


@app.delete("/conversations/{conversation_id}/messages")
def clear_conversation(conversation_id: str, client_id: str = Query(..., min_length=1, max_length=100)):
    if not conversation_belongs_to_client(conversation_id, client_id):
        raise HTTPException(404, "Conversation not found")
    clear_messages(conversation_id)
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    conversation_id = req.conversation_id
    if conversation_id is None:
        conversation_id = create_conversation(req.client_id)["id"]
    elif not conversation_belongs_to_client(conversation_id, req.client_id):
        raise HTTPException(404, "Conversation not found")

    set_title_if_new(conversation_id, req.query)
    add_message(conversation_id, "user", req.query)
    try:
        if not GROQ_API_KEY:
            raise HTTPException(500, "GROQ_API_KEY not set")

        context = retrieve_context(req.query, k=req.k or 6)
        route = decide_route(req.query)
        print(f"[route] '{req.query[:60]}...' → {route}")
        model_used = LARGE_MODEL if route == "large" else SMALL_MODEL
        call_started = time.perf_counter()
        if route == "large":
            answer = call_large(context, req.query)
        else:
            answer = call_small(context, req.query)
        metrics.record_call(
            route, model_used, True, (time.perf_counter() - call_started) * 1000
        )
        metrics.record_request(True)
    except HTTPException:
        add_message(conversation_id, "bot", "Request failed", is_error=True)
        metrics.record_request(False)
        raise
    except Exception as e:
        if "route" in locals() and "call_started" in locals():
            metrics.record_call(
                route,
                model_used,
                False,
                (time.perf_counter() - call_started) * 1000,
                type(e).__name__,
            )
        metrics.record_request(False)
        add_message(conversation_id, "bot", f"Request failed: {e}", is_error=True)
        if "route" in locals() and "call_started" in locals():
            raise HTTPException(502, f"LLM call failed ({route}): {e}") from e
        raise HTTPException(500, f"Request failed: {e}") from e

    preview = context[:300] + ("..." if len(context) > 300 else "")
    add_message(
        conversation_id,
        "bot",
        answer,
        route=route,
        model=model_used,
    )

    return ChatResponse(
        answer=answer,
        model=model_used,
        route=route,
        context_preview=preview,
        conversation_id=conversation_id,
    )


FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return FileResponse(FRONTEND_DIR / "dashboard.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)