from dataclasses import dataclass
from datetime import datetime


@dataclass
class Event:
    event_type: str
    track_id: int
    class_name: str
    timestamp: datetime

    zone: str | None = None

    confidence: float = 1.0

    description: str = ""