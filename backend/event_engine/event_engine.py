from datetime import datetime
from math import sqrt

from backend.schemas.event import Event
from backend.schemas.object_state import ObjectState
from backend.event_engine.zone import Zone


class EventEngine:

    def __init__(self):

        # ----------------------------------
        # Zones
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
        # Normal event thresholds
        # ----------------------------------

        self.loitering_threshold = 10.0
        self.running_threshold = 15.0

        # ----------------------------------
        # Unattended object settings
        # ----------------------------------

        self.association_distance = 350.0
        self.separation_distance = 250.0
        self.unattended_threshold = 5.0

        # ----------------------------------
        # Object classes that may become
        # unattended
        # ----------------------------------

        self.unattended_classes = {
            "bottle",
            "backpack",
            "handbag",
            "suitcase",
            "laptop",
        }

        # ----------------------------------
        # Internal memory
        # ----------------------------------

        # Track ID -> previous zone
        self.previous_zones: dict[
            int,
            str | None
        ] = {}

        # Object track ID -> person track ID
        self.object_person_association: dict[
            int,
            int
        ] = {}

        # Object track ID -> separation start time
        self.separation_times: dict[
            int,
            datetime
        ] = {}

        # Person track ID -> last known position
        self.person_last_positions: dict[
            int,
            tuple[float, float]
        ] = {}

    # ======================================
    # MAIN UPDATE
    # ======================================

    def update(
        self,
        states: list[ObjectState],
        timestamp: datetime,
    ) -> list[Event]:

        events: list[Event] = []

        # ----------------------------------
        # Only active states
        # ----------------------------------

        active_states = [
            state
            for state in states
            if state.status == "ACTIVE"
        ]

        # ----------------------------------
        # Update zones for ALL objects
        # ----------------------------------

        for state in active_states:

            state.current_zone = self.get_zone(
                state.current_box.center
            )

        # ----------------------------------
        # Store latest person positions
        # ----------------------------------

        people = [
            state
            for state in active_states
            if state.class_name == "person"
        ]

        for person in people:

            self.person_last_positions[
                person.track_id
            ] = person.current_box.center

        # ==================================
        # PERSON EVENTS
        # ==================================

        for state in people:

            current_zone = state.current_zone

            previous_zone = self.previous_zones.get(
                state.track_id
            )

            # ----------------------------------
            # PERSON ENTERED
            # ----------------------------------

            if (
                current_zone is not None
                and previous_zone is None
            ):

                state.zone_entered_at = timestamp
                state.loitering = False

                events.append(
                    Event(
                        event_type="PERSON_ENTERED",
                        track_id=state.track_id,
                        class_name="person",
                        timestamp=timestamp,
                        zone=current_zone,
                        description=(
                            f"Person ID {state.track_id} "
                            f"entered {current_zone} zone."
                        ),
                    )
                )

            # ----------------------------------
            # PERSON EXITED
            # ----------------------------------

            elif (
                current_zone is None
                and previous_zone is not None
            ):

                state.zone_entered_at = None
                state.loitering = False

                events.append(
                    Event(
                        event_type="PERSON_EXITED",
                        track_id=state.track_id,
                        class_name="person",
                        timestamp=timestamp,
                        zone=previous_zone,
                        description=(
                            f"Person ID {state.track_id} "
                            f"exited {previous_zone} zone."
                        ),
                    )
                )

            # ----------------------------------
            # ZONE CHANGED
            # ----------------------------------

            elif (
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
                        class_name="person",
                        timestamp=timestamp,
                        zone=current_zone,
                        description=(
                            f"Person ID {state.track_id} "
                            f"moved from {previous_zone} "
                            f"to {current_zone}."
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
                    timestamp
                    - state.zone_entered_at
                ).total_seconds()

                if (
                    dwell_time
                    >= self.loitering_threshold
                ):

                    state.loitering = True

                    events.append(
                        Event(
                            event_type="LOITERING",
                            track_id=state.track_id,
                            class_name="person",
                            timestamp=timestamp,
                            zone=current_zone,
                            description=(
                                f"Person ID {state.track_id} "
                                f"has remained in "
                                f"{current_zone} zone for "
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
                speed >= self.running_threshold
                and not state.running
            ):

                state.running = True

                events.append(
                    Event(
                        event_type="RUNNING",
                        track_id=state.track_id,
                        class_name="person",
                        timestamp=timestamp,
                        zone=current_zone,
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

            self.previous_zones[
                state.track_id
            ] = current_zone

        # ==================================
        # UNATTENDED OBJECTS
        # ==================================

        objects = [
            state
            for state in active_states
            if state.class_name
            in self.unattended_classes
        ]

        self.detect_unattended(
            objects,
            people,
            timestamp,
            events,
        )

        return events

    # ======================================
    # UNATTENDED OBJECT DETECTION
    # ======================================

    def detect_unattended(
        self,
        objects: list[ObjectState],
        people: list[ObjectState],
        timestamp: datetime,
        events: list[Event],
    ):

        for obj in objects:

            object_center = (
                obj.current_box.center
            )

            # ----------------------------------
            # Existing association
            # ----------------------------------

            person_id = (
                self.object_person_association.get(
                    obj.track_id
                )
            )

            # ----------------------------------
            # Find a person if no association
            # exists
            # ----------------------------------

            if person_id is None:

                nearest_person = None
                nearest_distance = float("inf")

                for person in people:

                    distance = self.distance(
                        object_center,
                        person.current_box.center,
                    )

                    if distance < nearest_distance:

                        nearest_distance = distance
                        nearest_person = person

                if (
                    nearest_person is not None
                    and nearest_distance
                    <= self.association_distance
                ):

                    person_id = (
                        nearest_person.track_id
                    )

                    self.object_person_association[
                        obj.track_id
                    ] = person_id

                    obj.unattended = False

                    self.separation_times.pop(
                        obj.track_id,
                        None,
                    )

                    print(
                        f"[ASSOCIATION] "
                        f"{obj.class_name} ID "
                        f"{obj.track_id} -> "
                        f"Person ID {person_id}"
                    )

                    continue

            # ----------------------------------
            # No association
            # ----------------------------------

            if person_id is None:
                continue

            # ----------------------------------
            # Retrieve last known person position
            # ----------------------------------

            person_position = (
                self.person_last_positions.get(
                    person_id
                )
            )

            if person_position is None:
                continue

            # ----------------------------------
            # Distance from object to person
            # ----------------------------------

            distance = self.distance(
                object_center,
                person_position,
            )

            # ----------------------------------
            # Person is still close
            # ----------------------------------

            if (
                distance
                <= self.separation_distance
            ):

                self.separation_times.pop(
                    obj.track_id,
                    None,
                )

                obj.unattended = False

                continue

            # ----------------------------------
            # Person has moved away
            # ----------------------------------

            if (
                obj.track_id
                not in self.separation_times
            ):

                self.separation_times[
                    obj.track_id
                ] = timestamp

                print(
                    f"[SEPARATED] "
                    f"{obj.class_name} ID "
                    f"{obj.track_id} from "
                    f"Person ID {person_id}"
                )

                continue

            # ----------------------------------
            # Check whether object is stationary
            # ----------------------------------

            if not self.is_stationary(obj):

                self.separation_times.pop(
                    obj.track_id,
                    None,
                )

                continue

            # ----------------------------------
            # Calculate unattended duration
            # ----------------------------------

            elapsed = (
                timestamp
                - self.separation_times[
                    obj.track_id
                ]
            ).total_seconds()

            print(
                f"[UNATTENDED CHECK] "
                f"{obj.class_name} ID "
                f"{obj.track_id} | "
                f"time={elapsed:.1f}s"
            )

            # ----------------------------------
            # Trigger unattended event
            # ----------------------------------

            if (
                elapsed
                >= self.unattended_threshold
                and not obj.unattended
            ):

                obj.unattended = True

                events.append(
                    Event(
                        event_type="UNATTENDED_OBJECT",
                        track_id=obj.track_id,
                        class_name=obj.class_name,
                        timestamp=timestamp,
                        zone=obj.current_zone,
                        confidence=1.0,
                        description=(
                            f"{obj.class_name} ID "
                            f"{obj.track_id} appears "
                            f"unattended. Associated "
                            f"person ID {person_id} "
                            f"moved away and the object "
                            f"remained stationary."
                        ),
                    )
                )

    # ======================================
    # STATIONARY OBJECT CHECK
    # ======================================

    def is_stationary(
        self,
        obj: ObjectState,
    ) -> bool:

        # Need enough position history
        if len(obj.position_history) < 8:
            return False

        recent_positions = (
            obj.position_history[-8:]
        )

        # ----------------------------------
        # Total displacement
        # ----------------------------------

        start_position = (
            recent_positions[0]
        )

        end_position = (
            recent_positions[-1]
        )

        displacement = self.distance(
            start_position,
            end_position,
        )

        # ----------------------------------
        # Total movement
        # ----------------------------------

        total_movement = 0.0

        for i in range(
            1,
            len(recent_positions),
        ):

            total_movement += self.distance(
                recent_positions[i - 1],
                recent_positions[i],
            )

        # ----------------------------------
        # Allow small tracking jitter
        # ----------------------------------

        return (
            displacement <= 60.0
            and total_movement <= 100.0
        )

    # ======================================
    # DISTANCE
    # ======================================

    @staticmethod
    def distance(
        point_a: tuple[float, float],
        point_b: tuple[float, float],
    ) -> float:

        dx = point_a[0] - point_b[0]
        dy = point_a[1] - point_b[1]

        return sqrt(
            dx ** 2
            + dy ** 2
        )

    # ======================================
    # ZONE
    # ======================================

    def get_zone(
        self,
        point: tuple[float, float],
    ) -> str | None:

        for zone in self.zones:

            if zone.contains(point):
                return zone.name

        return None