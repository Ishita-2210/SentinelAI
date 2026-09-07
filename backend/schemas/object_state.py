from dataclasses import dataclass, field
from datetime import datetime

from backend.schemas.bounding_box import BoundingBox


@dataclass
class ObjectState:
    track_id: int
    class_id: int
    class_name: str

    current_box: BoundingBox
    previous_box: BoundingBox | None = None

    first_seen: datetime | None = None
    last_seen: datetime | None = None

    position_history: list[tuple[float, float]] = field(
        default_factory=list
    )

    velocity: tuple[float, float] = (0.0, 0.0)

    current_zone: str | None = None