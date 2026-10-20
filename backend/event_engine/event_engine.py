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
        self.previous_zones: dict[int, str | None] = {}

        # Track ID -> first time we saw this person in any zone
        self.first_seen_in_zone: dict[int, datetime] = {}

        # Object track ID -> person track ID
        self.object_person_association: dict[int, int] = {}

        # Object track ID -> separation start time
        self.separation_times: dict[int, datetime] = {}

        # Person track ID -> last known position
        self.person_last_positions: dict[int, tuple[float, float]] = {}

        # Track IDs that have already triggered PERSON_ENTERED
        self._entered: set[int] = set()

        # Track IDs currently known to be in a zone (for exit detection)
        self._active_track_ids: set[int] = set()
        self._last_seen: dict[int, datetime] = {}
        self.missing_timeout = 1.0

    def reset(self):
        """Start a new source segment without carrying temporal claims across a seek."""
        self.previous_zones.clear()
        self.first_seen_in_zone.clear()
        self.object_person_association.clear()
        self.separation_times.clear()
        self.person_last_positions.clear()
        self._entered.clear()
        self._active_track_ids.clear()
        self._last_seen.clear()

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

        # Current track IDs visible this frame
        current_track_ids = {s.track_id for s in active_states}

        # ----------------------------------
        # Update zones for ALL objects
        # ----------------------------------

        for state in active_states:
            state.current_zone = self.get_zone(state.current_box.center)

        # ----------------------------------
        # Store latest person positions
        # ----------------------------------

        people = [
            state
            for state in active_states
            if state.class_name == "person"
        ]

        for person in people:
            self._last_seen[person.track_id] = timestamp
            self.person_last_positions[person.track_id] = (
                person.current_box.center
            )

        # ==================================
        # PERSON EVENTS
        # ==================================

        for state in people:

            current_zone = state.current_zone
            previous_zone = self.previous_zones.get(state.track_id)

            # ----------------------------------
            # PERSON ENTERED
            # ----------------------------------

            if (
                current_zone is not None
                and previous_zone is None
            ):

                self._entered.add(state.track_id)

                # Use first_seen so that if the engine missed the first
                # frame (e.g. empty states passed), dwell still accumulates
                # correctly from when the object was first detected.
                zone_start = timestamp
                state.zone_entered_at = zone_start
                self.first_seen_in_zone[state.track_id] = zone_start
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
            # ZONE CHANGED (already entered, moved to different zone)
            # ----------------------------------

            elif (
                current_zone is not None
                and previous_zone is not None
                and current_zone != previous_zone
            ):

                state.zone_entered_at = timestamp
                self.first_seen_in_zone[state.track_id] = timestamp
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
            # PERSON EXITED zone (still visible but left all zones)
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

            speed = sqrt(velocity_x ** 2 + velocity_y ** 2)

            if speed >= self.running_threshold:

                if not state.running:
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
                                f"(speed={speed:.1f} px/frame)."
                            ),
                        )
                    )

            else:
                # Reset so RUNNING can fire again if they accelerate later
                state.running = False

            # ----------------------------------
            # Save current zone
            # ----------------------------------

            self.previous_zones[state.track_id] = current_zone

        # ==================================
        # PERSON EXITED — track disappeared entirely
        # ==================================
        # Catch people who were in a zone last frame but are gone now.

        disappeared_track_ids = self._active_track_ids - current_track_ids

        pending = set()
        for tid in disappeared_track_ids:
            if (timestamp - self._last_seen[tid]).total_seconds() < self.missing_timeout:
                pending.add(tid)
                continue
            prev_zone = self.previous_zones.get(tid)
            if prev_zone is not None:
                events.append(
                    Event(
                        event_type="PERSON_EXITED",
                        track_id=tid,
                        class_name="person",
                        timestamp=timestamp,
                        zone=prev_zone,
                        description=(
                            f"Person ID {tid} "
                            f"left {prev_zone} zone "
                            f"(track lost)."
                        ),
                    )
                )
                # Clear so we don't fire again next frame
                self.previous_zones[tid] = None

        # Update active track set for next frame
        self._active_track_ids = {s.track_id for s in people} | pending

        # ==================================
        # UNATTENDED OBJECTS
        # ==================================

        objects = [
            state
            for state in active_states
            if state.class_name in self.unattended_classes
        ]

        self.detect_unattended(objects, people, timestamp, events)

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

            object_center = obj.current_box.center

            # ----------------------------------
            # Existing association
            # ----------------------------------

            person_id = self.object_person_association.get(obj.track_id)

            # ----------------------------------
            # Find a person if no association exists
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
                    and nearest_distance <= self.association_distance
                ):

                    person_id = nearest_person.track_id
                    self.object_person_association[obj.track_id] = person_id
                    obj.unattended = False
                    self.separation_times.pop(obj.track_id, None)
                    continue

            # ----------------------------------
            # No association found at all
            # ----------------------------------

            if person_id is None:
                continue

            # ----------------------------------
            # Retrieve last known person position
            # ----------------------------------

            person_position = self.person_last_positions.get(person_id)

            if person_position is None:
                continue

            # ----------------------------------
            # Distance from object to person
            # ----------------------------------

            distance = self.distance(object_center, person_position)

            # ----------------------------------
            # Person is still close
            # ----------------------------------

            owner_visible = any(p.track_id == person_id for p in people)
            if owner_visible and distance <= self.separation_distance:
                self.separation_times.pop(obj.track_id, None)
                obj.unattended = False
                continue

            # ----------------------------------
            # Person has moved away — start timer
            # ----------------------------------

            if obj.track_id not in self.separation_times:
                self.separation_times[obj.track_id] = timestamp
                continue

            # ----------------------------------
            # Check whether object is stationary
            # ----------------------------------

            if not self.is_stationary(obj):
                self.separation_times.pop(obj.track_id, None)
                continue

            # ----------------------------------
            # Calculate unattended duration
            # ----------------------------------

            elapsed = (
                timestamp - self.separation_times[obj.track_id]
            ).total_seconds()

            # ----------------------------------
            # Trigger unattended event
            # ----------------------------------

            if elapsed >= self.unattended_threshold and not obj.unattended:

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

    def is_stationary(self, obj: ObjectState) -> bool:

        if len(obj.position_history) < 8:
            return False

        recent_positions = obj.position_history[-8:]

        start_position = recent_positions[0]
        end_position = recent_positions[-1]

        displacement = self.distance(start_position, end_position)

        total_movement = 0.0
        for i in range(1, len(recent_positions)):
            total_movement += self.distance(
                recent_positions[i - 1],
                recent_positions[i],
            )

        return displacement <= 60.0 and total_movement <= 100.0

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
        return sqrt(dx ** 2 + dy ** 2)

    # ======================================
    # ZONE
    # ======================================

    def get_zone(self, point: tuple[float, float]) -> str | None:

        for zone in self.zones:
            if zone.contains(point):
                return zone.name

        return None