import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from backend.models import InvestigationResult

DEFAULT_DB_PATH = "claimcheck.db"


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create or connect to the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize database tables for ClaimCheck investigations."""
    with get_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY,
                pr_owner TEXT NOT NULL,
                pr_repo TEXT NOT NULL,
                pr_number INTEGER NOT NULL,
                pr_title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                result_json TEXT NOT NULL
            )
        """)
        conn.commit()


def save_investigation(result: InvestigationResult, db_path: str = DEFAULT_DB_PATH) -> None:
    """Persist an InvestigationResult into SQLite."""
    init_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    result_json = result.model_dump_json()

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO investigations 
            (id, pr_owner, pr_repo, pr_number, pr_title, created_at, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.investigation_id,
                result.pull_request.owner,
                result.pull_request.repo,
                result.pull_request.number,
                result.pull_request.title,
                now_iso,
                result_json,
            ),
        )
        conn.commit()


def get_investigation(investigation_id: str, db_path: str = DEFAULT_DB_PATH) -> InvestigationResult | None:
    """Retrieve an InvestigationResult by investigation_id."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT result_json FROM investigations WHERE id = ?",
            (investigation_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        data = json.loads(row["result_json"])
        return InvestigationResult.model_validate(data)


def list_investigations(limit: int = 20, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """List recent investigations for history and browsing."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            """
            SELECT id, pr_owner, pr_repo, pr_number, pr_title, created_at 
            FROM investigations 
            ORDER BY created_at DESC 
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

