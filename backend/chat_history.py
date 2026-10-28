import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("CHAT_DB_PATH", PROJECT_ROOT / "data" / "chat.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def initialize_database() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                is_error INTEGER NOT NULL DEFAULT 0,
                route TEXT,
                model TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_client_updated
                ON conversations(client_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id, id);
            """
        )


def create_conversation(client_id: str, title: str = "New chat") -> dict:
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO conversations (id, client_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, client_id, title, now, now),
        )
    return {"id": conversation_id, "title": title, "created_at": now, "updated_at": now}


def list_conversations(client_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE client_id = ?
              AND EXISTS (
                  SELECT 1 FROM messages WHERE messages.conversation_id = conversations.id
              )
            ORDER BY updated_at DESC
            """,
            (client_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def conversation_belongs_to_client(conversation_id: str, client_id: str) -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND client_id = ?",
            (conversation_id, client_id),
        ).fetchone()
    return row is not None


def add_message(
    conversation_id: str,
    role: str,
    text: str,
    is_error: bool = False,
    route: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO messages
                (conversation_id, role, text, is_error, route, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, text, int(is_error), route, model, now),
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )


def set_title_if_new(conversation_id: str, title: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE conversations
            SET title = ?, updated_at = ?
            WHERE id = ? AND title = 'New chat'
            """,
            (title, now, conversation_id),
        )


def get_messages(conversation_id: str, client_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT m.role, m.text, m.is_error, m.route, m.model, m.created_at
            FROM messages AS m
            JOIN conversations AS c ON c.id = m.conversation_id
            WHERE m.conversation_id = ? AND c.client_id = ?
            ORDER BY m.id
            """,
            (conversation_id, client_id),
        ).fetchall()
    return [
        {
            **dict(row),
            "is_error": bool(row["is_error"]),
            "meta": {"route": row["route"], "model": row["model"]}
            if row["route"]
            else None,
        }
        for row in rows
    ]


def clear_messages(conversation_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        connection.execute(
            "UPDATE conversations SET title = 'New chat', updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
