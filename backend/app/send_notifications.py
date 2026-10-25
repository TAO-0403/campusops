import argparse
import time

from app.config import email_notifications_enabled
from app.notifications import process_one_notification


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver queued CampusOps email notifications over SMTP.")
    parser.add_argument("--once", action="store_true", help="Process one notification and exit.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between checks in loop mode.")
    parser.add_argument("--retry-interval", type=int, default=30, help="Seconds before retrying a failed delivery.")
    args = parser.parse_args()
    if args.poll_interval <= 0 or args.retry_interval <= 0:
        parser.error("poll and retry intervals must be positive")
    if not email_notifications_enabled():
        parser.error("Email notifications are disabled. Set CAMPUSOPS_EMAIL_ENABLED=true to enable them.")

    if args.once:
        result = process_one_notification(args.retry_interval)
        print(f"Notification worker: {result}.")
        return

    print(f"Notification worker running; checking every {args.poll_interval:g} seconds. Press Ctrl+C to stop.")
    while True:
        result = process_one_notification(args.retry_interval)
        if result == "empty":
            time.sleep(args.poll_interval)
        elif result == "failed":
            time.sleep(min(args.poll_interval, args.retry_interval))


if __name__ == "__main__":
    main()
