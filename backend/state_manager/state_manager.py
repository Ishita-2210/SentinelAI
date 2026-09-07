from datetime import datetime

from backend.schemas.object_state import ObjectState
from backend.schemas.track import Track


class StateManager:

    def __init__(self):
        self.states: dict[int, ObjectState] = {}

    def update(
        self,
        tracks: list[Track],
        timestamp: datetime,
    ) -> list[ObjectState]:

        current_states = []

        for track in tracks:

            track_id = track.track_id
            current_box = track.bounding_box

            center_x, center_y = current_box.center

            # --------------------------------
            # New object
            # --------------------------------

            if track_id not in self.states:

                state = ObjectState(
                    track_id=track_id,
                    class_id=track.class_id,
                    class_name=track.class_name,
                    current_box=current_box,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    position_history=[
                        (center_x, center_y)
                    ],
                )

                self.states[track_id] = state

            # --------------------------------
            # Existing object
            # --------------------------------

            else:

                state = self.states[track_id]

                previous_center = state.current_box.center

                state.previous_box = state.current_box
                state.current_box = current_box

                state.last_seen = timestamp

                # Calculate movement
                previous_x, previous_y = previous_center

                velocity_x = center_x - previous_x
                velocity_y = center_y - previous_y

                state.velocity = (
                    velocity_x,
                    velocity_y,
                )

                # Store trajectory
                state.position_history.append(
                    (center_x, center_y)
                )

                # Keep history bounded
                if len(state.position_history) > 100:
                    state.position_history.pop(0)

            current_states.append(
                self.states[track_id]
            )

        return current_states