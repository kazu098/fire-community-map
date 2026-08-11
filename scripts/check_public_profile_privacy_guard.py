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

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def assert_database_publication_guard_exists() -> None:
    schema_sql = (PROJECT_ROOT / "supabase" / "public_profile_publication.sql").read_text()
    guard_sql = (PROJECT_ROOT / "supabase" / "public_profile_publication_guard.sql").read_text()
    combined_sql = schema_sql + "\n" + guard_sql
    required_fragments = [
        "prevent_implicit_public_profile_publication",
        "before insert or update on public.member_profiles",
        "update_member_profile_publication",
        "set_config('app.allow_public_profile_publication', 'on', true)",
        "security invoker",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in combined_sql]
    if missing:
        raise SystemExit("Database publication guard is missing: " + ", ".join(missing))


def assert_frontend_uses_publication_rpc() -> None:
    index_html = (PROJECT_ROOT / "index.html").read_text()
    if "/rest/v1/rpc/update_member_profile_publication" not in index_html:
        raise SystemExit("Public profile toggles must use update_member_profile_publication RPC.")


def main() -> int:
    assert_no_auto_public_flags_for_new_profile()
    assert_existing_flags_are_preserved()
    assert_database_publication_guard_exists()
    assert_frontend_uses_publication_rpc()
    print("Public profile privacy guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
