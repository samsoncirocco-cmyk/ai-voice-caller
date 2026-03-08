"""
db_engine.py — SQLAlchemy 2.0 engine + session factory for AI Voice Caller V2.

Database: campaigns/accounts.db  (same file as V1 — backward-compatible)

Usage:
    from execution.db_engine import get_session, engine
    with get_session() as session:
        account = session.get(Account, account_id)
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ── path resolution ──────────────────────────────────────────────────────────
# Supports override via env var (useful for testing)
_default_db = Path(__file__).resolve().parent.parent / "campaigns" / "accounts.db"
DB_PATH = Path(os.environ.get("VOICE_CALLER_DB", str(_default_db)))
DB_URL = f"sqlite:///{DB_PATH}"


# ── engine ───────────────────────────────────────────────────────────────────
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},  # SQLite multi-thread
    echo=False,
)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_conn, _record):
    """Enable WAL + foreign keys on every new connection."""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    dbapi_conn.execute("PRAGMA busy_timeout=5000")  # 5s wait on lock


# ── base ─────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── session factory ──────────────────────────────────────────────────────────
_SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context-manager session with auto-commit + rollback on error."""
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables that don't yet exist (idempotent)."""
    from execution.db_models import Base as _Base  # noqa: F401 — import side-effects
    _Base.metadata.create_all(engine)
