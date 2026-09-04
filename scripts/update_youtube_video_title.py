#!/usr/bin/env python3
"""Patch the snippet (title etc.) of an already-uploaded YouTube video.

Requires an OAuth token at data/.youtube_oauth_token.json — see
scripts/youtube_oauth_setup.py.

The youtube.upload scope doesn't permit videos.list, so this doesn't fetch
the existing snippet first — pass description/tags again if you don't want
them cleared (categoryId defaults to People & Blogs, matching the upload
script's default).

Usage:
  python3 scripts/update_youtube_video_title.py --video-id _45EHoORBYk \
    --title "FIRE、5年遅れて後悔 #Shorts" \
    --description-file /path/to/description.txt \
    --tags FIRE 早期リタイア
"""

from __future__ import annotations

import argparse
from pathlib import Path

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = REPO_ROOT / "data" / ".youtube_oauth_token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]
CATEGORY_ID_PEOPLE_AND_BLOGS = "22"


def load_credentials() -> Credentials:
    if not TOKEN_PATH.exists():
        raise SystemExit(f"Missing {TOKEN_PATH}. Run scripts/youtube_oauth_setup.py first.")
    credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
        TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--description-file", default=None, type=Path)
    parser.add_argument("--tags", nargs="*", default=[])
    args = parser.parse_args()

    description = args.description
    if args.description_file:
        description = args.description_file.read_text(encoding="utf-8")

    credentials = load_credentials()
    youtube = build("youtube", "v3", credentials=credentials)

    snippet = {
        "title": args.title,
        "description": description,
        "tags": args.tags,
        "categoryId": CATEGORY_ID_PEOPLE_AND_BLOGS,
    }
    youtube.videos().update(part="snippet", body={"id": args.video_id, "snippet": snippet}).execute()
    print(f"Updated title for https://youtu.be/{args.video_id}: {args.title}")


if __name__ == "__main__":
    main()
