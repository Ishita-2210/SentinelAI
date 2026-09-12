from datetime import datetime
from math import sqrt

from backend.schemas.event import Event
from backend.schemas.object_state import ObjectState
from backend.event_engine.zone import Zone


class EventEngine:

    def __init__(self):

        # ----------------------------------
        # Define zones
        # ----------------------------------

        self.zones = [
            Zone(
                name="entrance",
                x1=0,
                y1=0,
                x2=1000,
                y2=1000,
            )
        ]

        # ----------------------------------
        # Event configuration
        # ----------------------------------

        self.loitering_threshold = 10.0

        # Speed threshold for running
        self.running_threshold = 15.0

        # ----------------------------------
        # Previous zone tracking
        # ----------------------------------

        self.previous_zones: dict[int, str | None] = {}

    def update(
        self,
        states: list[ObjectState],
        timestamp: datetime,
    ) -> list[Event]:

        events: list[Event] = []

        for state in states:

            # Only process active objects
            if state.status != "ACTIVE":
                continue

            center = state.current_box.center

            # ----------------------------------
            # Determine current zone
            # ----------------------------------

            current_zone = self.get_zone(center)

            previous_zone = self.previous_zones.get(
                state.track_id
            )

            # ----------------------------------
            # ENTERED ZONE
            # ----------------------------------

            if (
                current_zone is not None
                and previous_zone is None
            ):

                state.zone_entered_at = timestamp
                state.loitering = False

                events.append(
                    Event(
                        event_type=f"{state.class_name.upper()}_ENTERED",
                        track_id=state.track_id,
                        class_name=state.class_name,
                        timestamp=timestamp,
                        zone=current_zone,
                        description=(
                            f"{state.class_name} entered "
                            f"{current_zone} zone."
                        ),
                    )
                )

            # ----------------------------------
            # EXITED ZONE
            # ----------------------------------

            if (
                current_zone is None
                and previous_zone is not None
            ):

                state.zone_entered_at = None
                state.loitering = False

                events.append(
                    Event(
                        event_type=f"{state.class_name.upper()}_EXITED",
                        track_id=state.track_id,
                        class_name=state.class_name,
                        timestamp=timestamp,
                        zone=previous_zone,
                        description=(
                            f"{state.class_name} exited "
                            f"{previous_zone} zone."
                        ),
                    )
                )

            # ----------------------------------
            # MOVED BETWEEN ZONES
            # ----------------------------------

            if (
                current_zone is not None
                and previous_zone is not None
                and current_zone != previous_zone
            ):

                state.zone_entered_at = timestamp
                state.loitering = False

                events.append(
                    Event(
                        event_type="ZONE_CHANGED",
                        track_id=state.track_id,
                        class_name=state.class_name,
                        timestamp=timestamp,
                        zone=current_zone,
                        description=(
                            f"{state.class_name} moved from "
                            f"{previous_zone} to {current_zone}."
                        ),
                    )
                )

            # ----------------------------------
            # LOITERING
            # ----------------------------------

            if (
                current_zone is not None
                and state.zone_entered_at is not None
                and not state.loitering
            ):

                dwell_time = (
                    timestamp - state.zone_entered_at
                ).total_seconds()

                if dwell_time >= self.loitering_threshold:

                    state.loitering = True

                    events.append(
                        Event(
                            event_type="LOITERING",
                            track_id=state.track_id,
                            class_name=state.class_name,
                            timestamp=timestamp,
                            zone=current_zone,
                            description=(
                                f"{state.class_name} has remained "
                                f"in {current_zone} zone for "
                                f"{dwell_time:.1f} seconds."
                            ),
                        )
                    )

            # ----------------------------------
            # RUNNING
            # ----------------------------------

            velocity_x, velocity_y = state.velocity

            speed = sqrt(
                velocity_x ** 2
                + velocity_y ** 2
            )

            if (
                state.class_name == "person"
                and speed >= self.running_threshold
                and not state.running
            ):

                state.running = True

                events.append(
                    Event(
                        event_type="RUNNING",
                        track_id=state.track_id,
                        class_name=state.class_name,
                        timestamp=timestamp,
                        zone=current_zone,
                        confidence=1.0,
                        description=(
                            f"Person ID {state.track_id} "
                            f"is moving rapidly "
                            f"(speed={speed:.1f})."
                        ),
                    )
                )

            elif speed < self.running_threshold:

                state.running = False

            # ----------------------------------
            # Save current zone
            # ----------------------------------

            self.previous_zones[state.track_id] = current_zone
            state.current_zone = current_zone

        return events

    def get_zone(
        self,
        point: tuple[float, float],
    ) -> str | None:

        for zone in self.zones:

            if zone.contains(point):
                return zone.name

        return None