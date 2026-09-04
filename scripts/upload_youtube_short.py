#!/usr/bin/env python3
"""Upload a rendered short to YouTube, optionally scheduled for later.

Requires an OAuth token at data/.youtube_oauth_token.json — see
scripts/youtube_oauth_setup.py for the one-time setup.

Usage:
  python3 scripts/upload_youtube_short.py \
    --file /path/to/short.mp4 \
    --title "FIRE、5年遅れて後悔 #Shorts" \
    --description-file /path/to/description.txt \
    --publish-at "2026-09-04T19:00:00+09:00" \
    --tags FIRE 早期リタイア 資産形成

With --publish-at, the video is uploaded as private and YouTube publishes it
automatically at that time (must be in the future). Without --publish-at,
--privacy controls the immediate visibility (default: private, so nothing
goes live by accident).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = REPO_ROOT / "data" / ".youtube_oauth_token.json"

SCOPES = ["https://www.googleapis.com/auth/youtube"]
CATEGORY_ID_PEOPLE_AND_BLOGS = "22"


def load_credentials() -> Credentials:
    if not TOKEN_PATH.exists():
        raise SystemExit(
            f"Missing {TOKEN_PATH}. Run scripts/youtube_oauth_setup.py first."
        )
    credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
        TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def parse_publish_at(value: str) -> str:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise SystemExit("--publish-at must include a UTC offset, e.g. +09:00")
    if dt <= datetime.now(timezone.utc):
        raise SystemExit("--publish-at must be in the future")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default=None)
    parser.add_argument("--description-file", default=None, type=Path)
    parser.add_argument("--tags", nargs="*", default=[])
    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
        help="Immediate visibility when --publish-at is not given.",
    )
    parser.add_argument(
        "--publish-at",
        default=None,
        help="ISO 8601 timestamp with UTC offset, e.g. 2026-09-04T19:00:00+09:00. "
        "Uploads as private and schedules automatic publish at this time.",
    )
    parser.add_argument("--made-for-kids", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.file.exists():
        raise SystemExit(f"File not found: {args.file}")

    if args.description and args.description_file:
        raise SystemExit("Use either --description or --description-file, not both")
    description = args.description or ""
    if args.description_file:
        description = args.description_file.read_text(encoding="utf-8")

    privacy_status = args.privacy
    publish_at = None
    if args.publish_at:
        publish_at = parse_publish_at(args.publish_at)
        privacy_status = "private"

    body = {
        "snippet": {
            "title": args.title,
            "description": description,
            "tags": args.tags,
            "categoryId": CATEGORY_ID_PEOPLE_AND_BLOGS,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": args.made_for_kids,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    print(f"file: {args.file}")
    print(f"title: {args.title}")
    print(f"privacyStatus: {privacy_status}")
    if publish_at:
        print(f"publishAt (UTC): {publish_at}")
    print(f"tags: {args.tags}")

    if args.dry_run:
        print("--dry-run: not uploading.")
        return

    credentials = load_credentials()
    youtube = build("youtube", "v3", credentials=credentials)

    media = MediaFileUpload(str(args.file), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  uploaded {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Uploaded: https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
