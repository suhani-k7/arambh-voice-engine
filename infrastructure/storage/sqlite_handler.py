import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from core.interfaces import StorageHandler
from utils.logger import AppLogger

logger = AppLogger.get_instance()

DB_DIR = Path(__file__).resolve().parent.parent.parent / "storage"
DEFAULT_DB_PATH = DB_DIR / "arambh.db"
TRANSCRIPTS_DIR = DB_DIR / "transcripts"


class SQLiteStorageHandler(StorageHandler):

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self) -> None:
        """Initialize database tables and storage folders."""
        if self._initialized:
            return
        await asyncio.to_thread(self._sync_initialize)
        self._initialized = True

    def _sync_initialize(self) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA foreign_keys = ON;")

            # Calls table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calls (
                    call_sid TEXT PRIMARY KEY,
                    stream_sid TEXT,
                    stage TEXT,
                    turn_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'in_progress',
                    started_at TEXT,
                    ended_at TEXT,
                    duration_seconds REAL DEFAULT 0.0,
                    created_at TEXT
                )
            """)

            # Borrowers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS borrowers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_sid TEXT UNIQUE,
                    name TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    loan_amount TEXT DEFAULT '',
                    monthly_income TEXT DEFAULT '',
                    loan_purpose TEXT DEFAULT '',
                    is_complete INTEGER DEFAULT 0,
                    updated_at TEXT,
                    FOREIGN KEY (call_sid) REFERENCES calls (call_sid) ON DELETE CASCADE
                )
            """)

            # Transcripts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_sid TEXT,
                    turn_index INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT,
                    FOREIGN KEY (call_sid) REFERENCES calls (call_sid) ON DELETE CASCADE
                )
            """)
            conn.commit()
            logger.info("SQLite storage initialized at: %s", self._db_path)

    async def save_call(self, call_data: dict) -> None:
        await self.initialize()
        await asyncio.to_thread(self._sync_save_call, call_data)

    def _sync_save_call(self, data: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO calls (call_sid, stream_sid, stage, turn_count, status, started_at, ended_at, duration_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_sid) DO UPDATE SET
                    stream_sid = COALESCE(excluded.stream_sid, calls.stream_sid),
                    stage = excluded.stage,
                    turn_count = excluded.turn_count,
                    status = excluded.status,
                    started_at = COALESCE(calls.started_at, excluded.started_at),
                    ended_at = excluded.ended_at,
                    duration_seconds = excluded.duration_seconds;
            """, (
                data.get("call_sid"),
                data.get("stream_sid", ""),
                data.get("stage", ""),
                data.get("turn_count", 0),
                data.get("status", "in_progress"),
                data.get("started_at", now),
                data.get("ended_at", ""),
                data.get("duration_seconds", 0.0),
                now,
            ))
            conn.commit()
            logger.info("Saved call metadata for call_sid: %s (status: %s)", data.get("call_sid"), data.get("status"))

    async def save_borrower_profile(self, call_sid: str, profile_dict: dict) -> None:
        await self.initialize()
        await asyncio.to_thread(self._sync_save_borrower_profile, call_sid, profile_dict)

    def _sync_save_borrower_profile(self, call_sid: str, profile: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        is_complete_val = 1 if profile.get("is_complete") else 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO borrowers (call_sid, name, phone, loan_amount, monthly_income, loan_purpose, is_complete, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(call_sid) DO UPDATE SET
                    name = excluded.name,
                    phone = excluded.phone,
                    loan_amount = excluded.loan_amount,
                    monthly_income = excluded.monthly_income,
                    loan_purpose = excluded.loan_purpose,
                    is_complete = excluded.is_complete,
                    updated_at = excluded.updated_at;
            """, (
                call_sid,
                profile.get("name", ""),
                profile.get("phone", ""),
                profile.get("loan_amount", ""),
                profile.get("monthly_income", ""),
                profile.get("loan_purpose", ""),
                is_complete_val,
                now,
            ))
            conn.commit()
            logger.info("Persisted borrower profile for call_sid: %s (name: %s, complete: %s)", call_sid, profile.get("name"), is_complete_val)

    async def save_transcript(self, call_sid: str, history: list[dict]) -> None:
        await self.initialize()
        await asyncio.to_thread(self._sync_save_transcript, call_sid, history)

    def _sync_save_transcript(self, call_sid: str, history: list[dict]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Clear previous turns for this call if any to avoid duplicates
            cursor.execute("DELETE FROM transcripts WHERE call_sid = ?", (call_sid,))

            for idx, msg in enumerate(history):
                cursor.execute("""
                    INSERT INTO transcripts (call_sid, turn_index, role, content, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    call_sid,
                    idx + 1,
                    msg.get("role", ""),
                    msg.get("content", ""),
                    msg.get("timestamp", datetime.now(timezone.utc).isoformat()),
                ))
            conn.commit()

        # Also write clean JSON file archive
        try:
            TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            json_file = TRANSCRIPTS_DIR / f"{call_sid}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump({
                    "call_sid": call_sid,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "turns_count": len(history),
                    "transcript": history
                }, f, indent=2, ensure_ascii=False)
            logger.info("Saved %d transcript turns & JSON file for call_sid: %s", len(history), call_sid)
        except Exception as e:
            logger.error("Failed to write transcript JSON file for %s: %s", call_sid, e)

    async def get_borrower_profile(self, call_sid: str) -> dict | None:
        await self.initialize()
        return await asyncio.to_thread(self._sync_get_borrower_profile, call_sid)

    def _sync_get_borrower_profile(self, call_sid: str) -> dict | None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, c.status as call_status, c.duration_seconds, c.started_at, c.ended_at, c.turn_count
                FROM borrowers b
                LEFT JOIN calls c ON b.call_sid = c.call_sid
                WHERE b.call_sid = ?
            """, (call_sid,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    async def get_all_borrowers(self) -> list[dict]:
        await self.initialize()
        return await asyncio.to_thread(self._sync_get_all_borrowers)

    def _sync_get_all_borrowers(self) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, c.status as call_status, c.duration_seconds, c.started_at, c.ended_at, c.turn_count
                FROM borrowers b
                LEFT JOIN calls c ON b.call_sid = c.call_sid
                ORDER BY b.updated_at DESC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_call_transcript(self, call_sid: str) -> list[dict]:
        await self.initialize()
        return await asyncio.to_thread(self._sync_get_call_transcript, call_sid)

    def _sync_get_call_transcript(self, call_sid: str) -> list[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT turn_index, role, content, timestamp
                FROM transcripts
                WHERE call_sid = ?
                ORDER BY turn_index ASC
            """, (call_sid,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
