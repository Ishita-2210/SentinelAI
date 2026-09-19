from datetime import datetime
from math import sqrt

from backend.schemas.event import Event
from backend.schemas.object_state import ObjectState
from backend.event_engine.zone import Zone


class EventEngine:

    def __init__(self):

        self.zones = [
            Zone(
                name="entrance",
                x1=0,
                y1=0,
                x2=1000,
                y2=1000,
            )
        ]

        # Normal events
        self.loitering_threshold = 10.0
        self.running_threshold = 15.0

        # Unattended test settings
        self.association_distance = 350.0
        self.separation_distance = 250.0
        self.unattended_threshold = 5.0

        # More forgiving stationary detection
        self.stationary_speed_threshold = 15.0
        self.stationary_displacement_threshold = 40.0

        self.unattended_classes = {
            "bottle",
            "backpack",
            "handbag",
            "suitcase",
            "laptop",
        }

        self.previous_zones = {}

        # object_id -> person_id
        self.object_person_association = {}

        # object_id -> time separation started
        self.separation_times = {}

        # Remember last known person position
        self.person_last_positions = {}

    def update(self, states, timestamp):

        events = []

        active_states = [
            state
            for state in states
            if state.status == "ACTIVE"
        ]

        # ----------------------------------
        # Remember people positions
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

        # ----------------------------------
        # Person events
        # ----------------------------------

        for state in people:

            current_zone = self.get_zone(
                state.current_box.center
            )

            previous_zone = self.previous_zones.get(
                state.track_id
            )

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

            # Loitering
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

            # Running
            vx, vy = state.velocity

            speed = sqrt(vx ** 2 + vy ** 2)

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

            self.previous_zones[
                state.track_id
            ] = current_zone

            state.current_zone = current_zone

        # ----------------------------------
        # Unattended objects
        # ----------------------------------

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

    def detect_unattended(
        self,
        objects,
        people,
        timestamp,
        events,
    ):

        for obj in objects:

            object_center = obj.current_box.center

            person_id = (
                self.object_person_association.get(
                    obj.track_id
                )
            )

            # ==================================
            # STEP 1: find association
            # ==================================

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

                    person_id = nearest_person.track_id

                    self.object_person_association[
                        obj.track_id
                    ] = person_id

                    obj.unattended = False

                    print(
                        f"[ASSOCIATION] "
                        f"{obj.class_name} ID "
                        f"{obj.track_id} -> "
                        f"Person ID {person_id}"
                    )

                    continue

            # No person association yet
            if person_id is None:
                continue

            # ==================================
            # STEP 2: determine person distance
            # ==================================

            person_position = (
                self.person_last_positions.get(
                    person_id
                )
            )

            if person_position is None:
                continue

            distance = self.distance(
                object_center,
                person_position,
            )

            # ==================================
            # STEP 3: person still close
            # ==================================

            if distance <= self.separation_distance:

                self.separation_times.pop(
                    obj.track_id,
                    None,
                )

                obj.unattended = False

                continue

            # ==================================
            # STEP 4: person moved away
            # ==================================

            if obj.track_id not in self.separation_times:

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

            # ==================================
            # STEP 5: object stationary?
            # ==================================

            if not self.is_stationary(obj):

                self.separation_times.pop(
                    obj.track_id,
                    None,
                )

                continue

            # ==================================
            # STEP 6: unattended timer
            # ==================================

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

            if (
                elapsed >= self.unattended_threshold
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

    def is_stationary(self, obj):

        vx, vy = obj.velocity

        speed = sqrt(
            vx ** 2 + vy ** 2
        )

        if speed > self.stationary_speed_threshold:
            return False

        if len(obj.position_history) < 5:
            return False

        positions = obj.position_history[-5:]

        displacement = self.distance(
            positions[0],
            positions[-1],
        )

        return (
            displacement
            <= self.stationary_displacement_threshold
        )

    @staticmethod
    def distance(a, b):

        dx = a[0] - b[0]
        dy = a[1] - b[1]

        return sqrt(
            dx ** 2
            + dy ** 2
        )

    def get_zone(self, point):

        for zone in self.zones:

            if zone.contains(point):
                return zone.name

        return None