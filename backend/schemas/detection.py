from dataclasses import dataclass

@dataclass
class Detection:

    class_id: int
    class_name: str

    confidence: float

    x1: float
    y1: float
    x2: float
    y2: float