from dataclasses import dataclass


@dataclass
class Zone:
    name: str

    x1: float
    y1: float
    x2: float
    y2: float

    def contains(self, point: tuple[float, float]) -> bool:
        x, y = point

        return (
            self.x1 <= x <= self.x2
            and self.y1 <= y <= self.y2
        )