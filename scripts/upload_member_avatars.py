#!/usr/bin/env python3
"""Upload matched Discord member avatars to Supabase Storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


USER_AGENT = "fire-community-map-avatar-uploader/0.1"
DEFAULT_BUCKET = "member-avatars"
MAX_AVATAR_BYTES = 2 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


@dataclass(frozen=True)
class AvatarUpload:
    sheet_row: int
    nickname: str
    avatar_url: str
    avatar_hash: str | None
    avatar_source: str
    avatar_path: str
    content_type: str | None
    uploaded: bool
    skipped: bool
    error: str | None


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def read_matches(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("matched") or [])


def infer_extension_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    suffix = Path(path).suffix.lstrip(".")
    if suffix in {"png", "jpg", "jpeg", "gif", "webp"}:
        return "jpg" if suffix == "jpeg" else suffix
    return "png"


def build_avatar_path(member: dict[str, Any]) -> str:
    nickname = str(member["nickname"])
    sheet_row = int(member["sheet_row"])
    digest = hashlib.sha256(nickname.encode("utf-8")).hexdigest()[:12]
    ext = infer_extension_from_url(str(member["avatar_url"]))
    return f"members/row-{sheet_row:04d}-{digest}.{ext}"


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        body = exc.read()
        raise RuntimeError(
            f"HTTP error {exc.code} {method} {url}: {body.decode('utf-8', errors='replace')}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed {method} {url}: {exc}") from exc


def download_avatar(url: str, max_bytes: int) -> tuple[bytes, str]:
    status, headers, body = http_request(url, timeout=30)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Avatar download returned HTTP {status}")
    if len(body) > max_bytes:
        raise RuntimeError(f"Avatar is too large: {len(body)} bytes")

    content_type = headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        guessed_type, _ = mimetypes.guess_type(urlparse(url).path)
        content_type = (guessed_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise RuntimeError(f"Unsupported avatar content type: {content_type or 'unknown'}")

    return body, content_type


def supabase_headers(service_role_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
    }
    headers.update(extra or {})
    return headers


def ensure_bucket(supabase_url: str, service_role_key: str, bucket: str, public: bool) -> None:
    url = f"{supabase_url.rstrip('/')}/storage/v1/bucket"
    payload = json.dumps({"id": bucket, "name": bucket, "public": public}).encode("utf-8")
    try:
        http_request(
            url,
            method="POST",
            headers=supabase_headers(service_role_key, {"Content-Type": "application/json"}),
            data=payload,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "already exists" in message or "Duplicate" in message or "409" in message:
            return
        raise


def upload_object(
    supabase_url: str,
    service_role_key: str,
    bucket: str,
    path: str,
    body: bytes,
    content_type: str,
) -> None:
    url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{path}"
    http_request(
        url,
        method="POST",
        headers=supabase_headers(
            service_role_key,
            {
                "Content-Type": content_type,
                "Cache-Control": "31536000",
                "x-upsert": "true",
            },
        ),
        data=body,
        timeout=60,
    )


def process_member(
    member: dict[str, Any],
    *,
    supabase_url: str | None,
    service_role_key: str | None,
    bucket: str,
    dry_run: bool,
    max_bytes: int,
) -> AvatarUpload:
    avatar_path = build_avatar_path(member)
    base = {
        "sheet_row": int(member["sheet_row"]),
        "nickname": str(member["nickname"]),
        "avatar_url": str(member["avatar_url"]),
        "avatar_hash": member.get("avatar_hash"),
        "avatar_source": str(member.get("avatar_source") or ""),
        "avatar_path": f"{bucket}/{avatar_path}",
    }
    if dry_run:
        return AvatarUpload(**base, content_type=None, uploaded=False, skipped=True, error=None)

    try:
        assert supabase_url is not None
        assert service_role_key is not None
        body, content_type = download_avatar(base["avatar_url"], max_bytes)
        upload_object(supabase_url, service_role_key, bucket, avatar_path, body, content_type)
        return AvatarUpload(**base, content_type=content_type, uploaded=True, skipped=False, error=None)
    except Exception as exc:
        return AvatarUpload(
            **base,
            content_type=None,
            uploaded=False,
            skipped=False,
            error=str(exc),
        )


def write_report(path: Path, rows: list[AvatarUpload]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(rows),
            "uploaded": sum(1 for row in rows if row.uploaded),
            "skipped": sum(1 for row in rows if row.skipped),
            "errors": sum(1 for row in rows if row.error),
        },
        "avatars": [row.__dict__ for row in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload Discord member avatars from match report to Supabase Storage."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--matches", default="tmp/member_avatar_matches.json")
    parser.add_argument("--output", default="tmp/member_avatar_storage_paths.json")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--private-bucket", action="store_true")
    parser.add_argument("--create-bucket", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=MAX_AVATAR_BYTES)
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    supabase_url = None
    service_role_key = None
    if not args.dry_run:
        supabase_url = require_env("SUPABASE_URL")
        service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
        if args.create_bucket:
            ensure_bucket(
                supabase_url,
                service_role_key,
                args.bucket,
                public=not args.private_bucket,
            )

    members = read_matches(Path(args.matches))
    uploads: list[AvatarUpload] = []
    for index, member in enumerate(members, start=1):
        uploads.append(
            process_member(
                member,
                supabase_url=supabase_url,
                service_role_key=service_role_key,
                bucket=args.bucket,
                dry_run=args.dry_run,
                max_bytes=args.max_bytes,
            )
        )
        if not args.dry_run and index % 10 == 0:
            time.sleep(0.25)

    write_report(Path(args.output), uploads)
    errors = [row for row in uploads if row.error]
    print(
        "Processed {total} avatars ({uploaded} uploaded, {skipped} skipped, {errors} errors).".format(
            total=len(uploads),
            uploaded=sum(1 for row in uploads if row.uploaded),
            skipped=sum(1 for row in uploads if row.skipped),
            errors=len(errors),
        )
    )
    print(f"Wrote {args.output}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
