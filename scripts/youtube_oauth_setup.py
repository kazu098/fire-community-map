#!/usr/bin/env python3
"""One-time OAuth setup for uploading videos to YouTube.

This is separate from YOUTUBE_API_KEY (read-only, used by
notify_youtube_comments.py). Uploading requires a real OAuth login as the
channel owner.

Prerequisites (done once, in Google Cloud Console, by a human):
  1. https://console.cloud.google.com/ -> create/select a project.
  2. APIs & Services -> Library -> enable "YouTube Data API v3".
  3. APIs & Services -> OAuth consent screen -> configure as "External" (or
     "Internal" if using Workspace), add your own Google account as a test
     user if the app stays in "Testing" status.
  4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
     -> Application type "Desktop app". Download the JSON.
  5. Save that file as data/.youtube_oauth_client.json (gitignored).

Then run this script locally:
  python3 scripts/youtube_oauth_setup.py

It opens a browser for you to log in as the channel owner and grant access,
then saves a refresh token to data/.youtube_oauth_token.json (gitignored).
scripts/upload_youtube_short.py and scripts/update_youtube_video_title.py
read that token file.
"""

from __future__ import annotations

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

# youtube.upload alone can insert/delete videos but not videos.update
# (e.g. patching a title after upload), so use the full manage scope.
SCOPES = ["https://www.googleapis.com/auth/youtube"]

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET_PATH = REPO_ROOT / "data" / ".youtube_oauth_client.json"
TOKEN_PATH = REPO_ROOT / "data" / ".youtube_oauth_token.json"


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise SystemExit(
            f"Missing {CLIENT_SECRET_PATH}. Download an OAuth client (Desktop app) "
            "JSON from Google Cloud Console and save it there first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    credentials = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Saved refresh token to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
