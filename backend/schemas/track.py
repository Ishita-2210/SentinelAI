from dataclasses import dataclass

from backend.schemas.bounding_box import BoundingBox


@dataclass
class Track:
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    bounding_box: BoundingBox