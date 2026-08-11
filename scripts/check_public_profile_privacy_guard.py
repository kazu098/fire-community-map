#!/usr/bin/env python3
"""Guard against accidentally auto-enabling public member profile flags."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sync_member_profile_form_deltas import FormMember, build_profile_payload  # noqa: E402


PUBLIC_FIELDS = (
    "nickname_public",
    "avatar_public",
    "self_intro_public",
    "location_public",
    "links_public",
)


def assert_no_auto_public_flags_for_new_profile() -> None:
    member = FormMember(
        sheet_row=2,
        nickname="privacy-test",
        tags={"skill": ["テスト"]},
        links=[{"label": "note", "url": "https://note.com/example"}],
        external_self_intro_text="外部に出してはいけない自己紹介",
        location_text="東京都",
        avatar_url="https://example.com/avatar.png",
        self_intro_text="内部用自己紹介",
        self_intro_url="https://discord.com/channels/example",
        self_intro_posted_at="2026-08-11T00:00:00+00:00",
    )
    payload = build_profile_payload(member, None)
    enabled = [field for field in PUBLIC_FIELDS if payload.get(field) is not False]
    if enabled:
        raise SystemExit(
            "Public profile flags must never be auto-enabled for new profiles: "
            + ", ".join(enabled)
        )


def assert_existing_flags_are_preserved() -> None:
    existing = {
        "nickname": "privacy-test",
        "nickname_public": True,
        "avatar_public": False,
        "self_intro_public": True,
        "location_public": False,
        "links_public": True,
    }
    member = FormMember(
        sheet_row=2,
        nickname="privacy-test",
        tags={},
        links=[],
        external_self_intro_text="補完自己紹介",
    )
    payload = build_profile_payload(member, existing)
    for field in PUBLIC_FIELDS:
        if payload.get(field) != existing[field]:
            raise SystemExit(f"Public profile flag {field} was not preserved.")


def main() -> int:
    assert_no_auto_public_flags_for_new_profile()
    assert_existing_flags_are_preserved()
    print("Public profile privacy guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
