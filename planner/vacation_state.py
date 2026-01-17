"""
Vacation State Module

SQLite-backed state persistence for vacation mode features.
Uses the existing learning.sqlite_path database.

Rev K19: Anti-legionella cycle tracking.
"""

import logging
from datetime import datetime
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from backend.learning.models import VacationState

logger = logging.getLogger("darkstar.planner.vacation")


def _get_session(sqlite_path: str):
    """Get a SQLAlchemy session for the given database path."""
    engine = create_engine(f"sqlite:///{sqlite_path}", connect_args={"timeout": 30.0})
    Session = sessionmaker(bind=engine)
    return Session()


def load_last_anti_legionella(sqlite_path: str) -> datetime | None:
    """
    Load the last anti-legionella run timestamp from SQLite using SQLAlchemy.

    Args:
        sqlite_path: Path to the SQLite database file.

    Returns:
        datetime of last run, or None if never run.
    """
    try:
        with _get_session(sqlite_path) as session:
            result = session.get(VacationState, "last_anti_legionella_at")
            if result and result.value:
                return datetime.fromisoformat(result.value)
        return None
    except Exception as e:
        logger.warning("Failed to load last_anti_legionella_at: %s", e)
        return None


def save_last_anti_legionella(sqlite_path: str, timestamp: datetime) -> None:
    """
    Save the anti-legionella run timestamp to SQLite using SQLAlchemy.

    Args:
        sqlite_path: Path to the SQLite database file.
        timestamp: When the anti-legionella cycle was scheduled.
    """
    try:
        with _get_session(sqlite_path) as session:
            state = session.get(VacationState, "last_anti_legionella_at")
            if not state:
                state = VacationState(key="last_anti_legionella_at")
                session.add(state)
            
            state.value = timestamp.isoformat()
            state.updated_at = datetime.now().isoformat()
            session.commit()
            
        logger.info("Saved last_anti_legionella_at: %s", timestamp.isoformat())
    except Exception as e:
        logger.error("Failed to save last_anti_legionella_at: %s", e)
