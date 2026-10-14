
"""
RAG pipeline over Hull's Options, Futures, and Other Derivatives (8th ed).

Loads the PDF, splits it into chunks, embeds them, and persists a Chroma
vector store. Reuses a non-empty existing collection and rebuilds if the
collection is missing or empty.
"""

from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PDF_PATH = PROJECT_ROOT / "hulls-derivatives.pdf"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "hull_derivatives"

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

_embeddings: Optional[HuggingFaceEmbeddings] = None
_vectorstore: Optional[Chroma] = None


# ---------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------

def get_embeddings() -> HuggingFaceEmbeddings:
    """Initialize and cache the embedding model."""
    global _embeddings

    if _embeddings is None:
        print(f"[RAG] Loading embedding model: {EMBED_MODEL}")

        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

        print("[RAG] Embedding model loaded.")

    return _embeddings


# ---------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------

def build_vectorstore(force_rebuild: bool = False) -> Chroma:
    """
    Load an existing non-empty Chroma collection or build it from the PDF.

    Args:
        force_rebuild: Rebuild the collection even if it already contains
            documents.

    Returns:
        Initialized Chroma vector store.
    """
    global _vectorstore

    if _vectorstore is not None and not force_rebuild:
        count = _vectorstore._collection.count()

        if count > 0:
            return _vectorstore

        print("[RAG] Cached collection is empty; rebuilding.")
        _vectorstore = None

    embeddings = get_embeddings()

    # Check whether a persisted collection already contains documents.
    if CHROMA_DIR.exists() and not force_rebuild:
        print(f"[RAG] Checking existing store: {CHROMA_DIR}")

        existing = Chroma(
            collection_name=COLLECTION_NAME,
            persist_directory=str(CHROMA_DIR),
            embedding_function=embeddings,
        )

        count = existing._collection.count()
        print(f"[RAG] Existing collection contains {count} chunks.")

        if count > 0:
            _vectorstore = existing
            print("[RAG] Reusing existing vector store.")
            return _vectorstore

        print("[RAG] Collection is empty; indexing the PDF.")

    # Check the source PDF.
    if not PDF_PATH.is_file():
        raise FileNotFoundError(
            f"PDF not found at {PDF_PATH}. "
            "Ensure hulls-derivatives.pdf is in the project root."
        )

    # Load the PDF.
    print(f"[RAG] Loading PDF: {PDF_PATH}")

    loader = PyPDFLoader(str(PDF_PATH))
    documents = loader.load()

    print(f"[RAG] Loaded {len(documents)} pages.")

    if not documents:
        raise ValueError("The PDF loader returned no pages.")

    # Split the document into overlapping chunks.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = splitter.split_documents(documents)

    # Remove empty text chunks.
    chunks = [
        chunk
        for chunk in chunks
        if chunk.page_content and chunk.page_content.strip()
    ]

    print(f"[RAG] Created {len(chunks)} text chunks.")

    if not chunks:
        raise ValueError(
            "No text chunks were extracted from the PDF. "
            "The PDF may be scanned or contain no extractable text."
        )

    # Recreate the collection when rebuilding an existing index.
    if force_rebuild:
        print("[RAG] Rebuilding the existing collection.")
        existing = Chroma(
            collection_name=COLLECTION_NAME,
            persist_directory=str(CHROMA_DIR),
            embedding_function=embeddings,
        )
        existing.delete_collection()

    # Embed the chunks and persist them in Chroma.
    print("[RAG] Creating embeddings and indexing chunks...")

    _vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
    )

    final_count = _vectorstore._collection.count()

    print(f"[RAG] Vector store ready: {final_count} chunks indexed.")

    if final_count == 0:
        _vectorstore = None
        raise RuntimeError(
            "Chroma indexing finished, but the collection is empty."
        )

    return _vectorstore


# ---------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------

def get_retriever(k: int = 6):
    """Return a retriever configured to return the top k chunks."""
    if not 1 <= k <= 12:
        raise ValueError("k must be between 1 and 12.")

    vectorstore = build_vectorstore()

    return vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )


def retrieve_context(query: str, k: int = 6) -> str:
    """
    Retrieve relevant PDF passages for a question.

    Returns formatted passages with page numbers, or a diagnostic fallback
    message if the collection contains no documents or no results are found.
    """
    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    vectorstore = build_vectorstore()

    count = vectorstore._collection.count()

    if count == 0:
        return "No relevant passages found in the book: Chroma collection is empty."

    retriever = get_retriever(k=k)
    docs = retriever.invoke(query)

    if not docs:
        print(f"[RAG] No results returned for query: {query!r}")
        return "No relevant passages found in the book."

    parts = []

    for index, doc in enumerate(docs, start=1):
        page = doc.metadata.get("page", "?")

        # PyPDFLoader uses zero-based page numbers.
        if isinstance(page, int):
            page = page + 1

        content = doc.page_content.strip()

        if content:
            parts.append(
                f"[Passage {index} | page {page}]\n{content}"
            )

    if not parts:
        return "No relevant passages found in the book."

    print(
        f"[RAG] Retrieved {len(parts)} passages "
        f"for query: {query[:100]!r}"
    )

    return "\n\n---\n\n".join(parts)
