from datetime import datetime

from backend.schemas.object_state import ObjectState
from backend.schemas.track import Track


class StateManager:
    def __init__(self, missing_timeout: float = 1.0):
        self.states: dict[int, ObjectState] = {}
        self.missing_timeout = missing_timeout

    def update(
        self,
        tracks: list[Track],
        timestamp: datetime,
    ) -> list[ObjectState]:

        current_states = []
        current_track_ids = set()

        # -----------------------------------
        # 1. Update visible tracks
        # -----------------------------------

        for track in tracks:

            track_id = track.track_id
            current_track_ids.add(track_id)

            current_box = track.bounding_box
            center_x, center_y = current_box.center

            # New object
            if track_id not in self.states:

                state = ObjectState(
                    track_id=track_id,
                    class_id=track.class_id,
                    class_name=track.class_name,
                    current_box=current_box,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    position_history=[(center_x, center_y)],
                    status="ACTIVE",
                )

                self.states[track_id] = state

            # Existing object
            else:

                state = self.states[track_id]

                previous_center = state.current_box.center

                state.previous_box = state.current_box
                state.current_box = current_box

                elapsed = max((timestamp - state.last_seen).total_seconds(), 1e-6)
                state.last_seen = timestamp

                previous_x, previous_y = previous_center

                velocity_x = (center_x - previous_x) / (elapsed * 30.0)
                velocity_y = (center_y - previous_y) / (elapsed * 30.0)

                state.velocity = (
                    velocity_x,
                    velocity_y,
                )

                state.position_history.append(
                    (center_x, center_y)
                )

                if len(state.position_history) > 100:
                    state.position_history.pop(0)

                # Object has reappeared
                state.status = "ACTIVE"
                state.missing_since = None

            current_states.append(self.states[track_id])

        # -----------------------------------
        # 2. Check missing objects
        # -----------------------------------

        for track_id, state in list(self.states.items()):

            if track_id in current_track_ids:
                continue

            if state.status == "REMOVED":
                del self.states[track_id]
                continue

            # Brief dropouts preserve identity. Long-expired tracks must not
            # retain an unbounded history or old dwell state when IDs recur.
            if (timestamp - state.last_seen).total_seconds() > max(30.0, self.missing_timeout * 2):
                del self.states[track_id]
                continue

            if state.missing_since is None:

                state.missing_since = timestamp
                state.status = "MISSING"

            else:

                missing_duration = (
                    timestamp - state.missing_since
                ).total_seconds()

                if missing_duration > self.missing_timeout:

                    state.status = "LOST"

        return current_states
