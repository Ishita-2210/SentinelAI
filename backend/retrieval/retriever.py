"""Retrieval over persistent event memory.

Turns a natural-language question ("was there an unattended bag in the last
hour?") into a filtered, ranked list of stored events. It is deliberately
deterministic and local: time window + event-type hints + SQLite FTS5.
The LLM only ever sees what this module returns.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.database.event_database import EVENT_COLUMNS, EventDatabase

# Words that carry no search value.
STOPWORDS = {
    "the", "a", "an", "is", "was", "were", "are", "did", "does", "do",
    "there", "any", "what", "when", "where", "who", "which", "how",
    "happened", "happen", "show", "tell", "me", "about", "of", "in",
    "on", "at", "to", "and", "or", "for", "with", "recently", "recent",
    "last", "past", "today", "yesterday", "ago", "has", "have", "had",
    "been", "evidence", "captured", "event", "events", "latest", "zone",
    "minutes", "minute", "hours", "hour", "days", "day", "please",
}

# Phrase -> event type. Checked in order; first group that matches wins
# (multiple groups can match and are combined).
EVENT_TYPE_HINTS = [
    (r"unattended|abandon|left behind|forgotten|unclaimed", "UNATTENDED_OBJECT"),
    (r"loiter|lingering|hanging around|waiting around", "LOITERING"),
    (r"\brun(ning|s)?\b|\bran\b|sprint", "RUNNING"),
    (r"\benter(ed|s)?\b|came in|arriv", "PERSON_ENTERED"),
    (r"\bexit(ed|s)?\b|\bleft the\b|\bleav(e|es|ing)\b|went out", "PERSON_EXITED"),
    (r"zone chang|moved (to|into)|changed zone|crossed", "ZONE_CHANGED"),
]


@dataclass
class QueryPlan:
    event_types: list[str]
    since: datetime | None
    until: datetime | None
    keywords: list[str]


def parse_time_window(
    question: str,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    """Extract a time window from phrases like 'last 30 minutes'."""

    text = question.lower()

    match = re.search(
        r"(?:last|past)\s+(\d+)\s*(minute|min|hour|hr|day)s?",
        text,
    )

    if match:
        amount = int(match.group(1))
        unit = match.group(2)

        if unit.startswith("min"):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)

        return now - delta, None

    if re.search(r"last\s+(an\s+)?hour|past\s+hour", text):
        return now - timedelta(hours=1), None

    if re.search(r"last\s+minute|past\s+minute", text):
        return now - timedelta(minutes=1), None

    if "yesterday" in text:
        start = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=1)
        return start, end

    if "today" in text:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, None

    return None, None


def plan_query(question: str, now: datetime) -> QueryPlan:

    text = question.lower()

    event_types = []
    for pattern, event_type in EVENT_TYPE_HINTS:
        if re.search(pattern, text) and event_type not in event_types:
            event_types.append(event_type)

    since, until = parse_time_window(question, now)

    tokens = re.findall(r"[a-z0-9_]+", text)
    keywords = [
        token
        for token in tokens
        if len(token) > 2 and token not in STOPWORDS and not token.isdigit()
    ]

    return QueryPlan(
        event_types=event_types,
        since=since,
        until=until,
        keywords=keywords,
    )


class EventRetriever:

    def __init__(self, database: EventDatabase):
        self.database = database

        # "fts", "like" or None (no keyword search yet). Useful in tests
        # and logs to see which path answered a query.
        self.last_search_mode: str | None = None

    # ---------------------------------
    # Public API
    # ---------------------------------

    def search(
        self,
        question: str,
        limit: int = 10,
        now: datetime | None = None,
    ) -> list[dict]:
        """Return events relevant to the question, newest/best first."""

        now = now or datetime.now()
        plan = plan_query(question, now)

        rows = self._run(plan, limit)

        return [self._to_dict(row) for row in rows]

    def recent(self, limit: int = 10) -> list[dict]:
        rows = self.database.get_recent_events(limit)
        return [self._to_dict(row) for row in rows]

    @staticmethod
    def format_context(events: list[dict]) -> str:
        """Render events as compact text for an LLM prompt."""

        lines = []

        for event in events:
            verification = event.get("verification") or "NOT_VERIFIED"
            detail = event.get("verification_detail") or ""

            line = (
                f"[event {event['id']}] {event['timestamp']} | "
                f"{event['event_type']} | {event['class_name']} "
                f"(track {event['track_id']}) | zone={event['zone']} | "
                f"engine: {event['description']} | "
                f"visual check: {verification}"
            )

            if detail:
                line += f" ({detail})"

            if event.get("evidence_path"):
                line += f" | evidence: {event['evidence_path']}"

            lines.append(line)

        return "\n".join(lines)

    # ---------------------------------
    # Internals
    # ---------------------------------

    def _run(self, plan: QueryPlan, limit: int) -> list[sqlite3.Row]:

        where = []
        params: list = []

        if plan.event_types:
            marks = ",".join("?" for _ in plan.event_types)
            where.append(f"e.event_type IN ({marks})")
            params.extend(plan.event_types)

        if plan.since:
            where.append("e.timestamp >= ?")
            params.append(plan.since.isoformat())

        if plan.until:
            where.append("e.timestamp <= ?")
            params.append(plan.until.isoformat())

        # Keyword text match only when the question did not already
        # resolve to specific event types (otherwise words like "bag"
        # would wrongly exclude valid events whose description differs).
        use_keywords = bool(plan.keywords) and not plan.event_types

        if use_keywords:
            rows = self._keyword_search(plan, where, params, limit)

            if rows:
                return rows

            # No text hit: fall back to time-filtered recency, but only
            # if the question had a time window. An unmatched topic with
            # no window returns nothing rather than unrelated events.
            if not (plan.since or plan.until):
                return []

        return self._filtered(where, params, limit)

    def _filtered(
        self,
        where: list[str],
        params: list,
        limit: int,
    ) -> list[sqlite3.Row]:

        clause = f"WHERE {' AND '.join(where)}" if where else ""

        sql = f"""
            SELECT {self._columns("e")}
            FROM events e
            {clause}
            ORDER BY e.id DESC
            LIMIT ?
        """

        return self.database.connection.execute(
            sql, [*params, limit]
        ).fetchall()

    def _keyword_search(
        self,
        plan: QueryPlan,
        where: list[str],
        params: list,
        limit: int,
    ) -> list[sqlite3.Row]:

        clause = f" AND {' AND '.join(where)}" if where else ""

        if self.database.fts_enabled:
            match_query = " OR ".join(
                f'"{keyword}"' for keyword in plan.keywords
            )

            sql = f"""
                SELECT {self._columns("e")}
                FROM events_fts
                JOIN events e ON e.id = events_fts.rowid
                WHERE events_fts MATCH ?{clause}
                ORDER BY bm25(events_fts), e.id DESC
                LIMIT ?
            """

            try:
                rows = self.database.connection.execute(
                    sql, [match_query, *params, limit]
                ).fetchall()

                self.last_search_mode = "fts"

                return rows
            except sqlite3.OperationalError:
                pass  # fall through to LIKE

        self.last_search_mode = "like"

        like_parts = []
        like_params: list = []

        for keyword in plan.keywords:
            like_parts.append(
                "(e.class_name LIKE ? OR e.description LIKE ? "
                "OR e.event_type LIKE ? OR e.zone LIKE ?)"
            )
            like_params.extend([f"%{keyword}%"] * 4)

        sql = f"""
            SELECT {self._columns("e")}
            FROM events e
            WHERE ({' OR '.join(like_parts)}){clause}
            ORDER BY e.id DESC
            LIMIT ?
        """

        return self.database.connection.execute(
            sql, [*like_params, *params, limit]
        ).fetchall()

    @staticmethod
    def _columns(alias: str) -> str:
        return ", ".join(
            f"{alias}.{column.strip()}"
            for column in EVENT_COLUMNS.split(",")
            if column.strip()
        )

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        return {key: row[key] for key in row.keys()}
