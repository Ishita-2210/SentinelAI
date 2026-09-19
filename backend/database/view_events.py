from backend.database.event_database import EventDatabase


def main():

    database = EventDatabase()

    events = database.get_recent_events(20)

    print("\n===== SENTINELAI EVENT HISTORY =====\n")

    for event in events:

        print(
            f"ID: {event['id']}\n"
            f"Type: {event['event_type']}\n"
            f"Object: {event['class_name']}\n"
            f"Track ID: {event['track_id']}\n"
            f"Time: {event['timestamp']}\n"
            f"Zone: {event['zone']}\n"
            f"Confidence: {event['confidence']}\n"
            f"Description: {event['description']}\n"
            f"Evidence: {event['evidence_path']}\n"
            f"{'-' * 50}"
        )

    print(
        f"\nTotal events: "
        f"{database.count_events()}"
    )

    database.close()


if __name__ == "__main__":
    main()