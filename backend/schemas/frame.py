from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass
class Frame:
    image: np.ndarray
    frame_id: int
    timestamp: datetime