"""
SentinelAI — Event Retrieval Layer

Provides structured queries over the SQLite event store. Returns plain
dicts rather than sqlite3.Row objects so results can be serialized by
FastAPI's JSON response machinery without additional adaptation.
"""
from __future__ import annotations

import logging
import json
from typing import Any

from backend.database.event_database import EventDatabase

logger = logging.getLogger(__name__)


def _row_to_dict(row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    result = dict(zip(row.keys(), tuple(row)))
    if result.get("source_metadata"):
        try:result["source_metadata"] = json.loads(result["source_metadata"])
        except (ValueError,TypeError):result["source_metadata"] = None
    result["vlm_confidence"] = None
    result["vlm_scope"] = ("model-generated still-image caption; temporal event is deterministic"
        if result.get("vlm_task") == "<DETAILED_CAPTION>" else
        "still-image presence only; temporal event is deterministic")
    return result


class EventRetriever:
    """
    Read-only retrieval interface over the EventDatabase.

    Decouples the API/LLM assistant from direct SQL access.
    All methods return plain dicts so they can be safely serialized.
    """

    def __init__(self, db: EventDatabase) -> None:
        self._db = db

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent events (newest first)."""
        rows = self._db.get_recent_events(limit=limit)
        return [_row_to_dict(r) for r in rows]

    def get_by_type(
        self, event_type: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._db.get_events_by_type(event_type=event_type, limit=limit)
        return [_row_to_dict(r) for r in rows]

    def get_by_id(self, event_id: int) -> dict[str, Any] | None:
        row = self._db.get_event_by_id(event_id)
        return _row_to_dict(row) if row is not None else None

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Full-text search on the event description column."""
        rows = self._db.search_events(query=query, limit=limit)
        return [_row_to_dict(r) for r in rows]

    def get_in_range(
        self, start_iso: str, end_iso: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = self._db.get_events_in_range(start_iso, end_iso, limit=limit)
        return [_row_to_dict(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        """Return event counts by type and total."""
        by_type = self._db.count_by_type()
        total = self._db.count_events()
        return {"total": total, "by_type": by_type}

    def for_question(self, question, limit=20, now=None, **overrides):
        from backend.retrival.questions import question_filters
        filters=question_filters(question,now=now,limit=limit)
        filters.update({k:v for k,v in overrides.items() if v is not None})
        return [_row_to_dict(x) for x in self._db.query_events(**filters)], filters
