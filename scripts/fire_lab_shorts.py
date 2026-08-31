#!/usr/bin/env python3
"""Create vertical YouTube Shorts from a YouTube video and a clip manifest.

This script intentionally keeps AI outside the renderer. Use an LLM to produce
or revise the JSON manifest, then render that manifest deterministically here.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_WORK_DIR = Path("/private/tmp/fire-lab-shorts")
CAPTION_GAP_TOLERANCE = 0.35
CAPTION_EDGE_TOLERANCE = 0.35
MAX_CAPTION_LINE_CHARS = 15
MAX_CAPTION_CHUNK_CHARS = 26
DEFAULT_WHISPER_MODEL = "large-v3"
WHISPER_MAX_GAP = 0.6
WHISPER_MIN_EVENT_CHARS = 8

# Full-width color bands, in the 1080x1920 output canvas. The video itself is
# padded to start at y=500 (see ffmpeg_filter), so the hook band sits flush
# against the top of the video with no gap. The footer band is pulled well up
# off the bottom edge so it doesn't collide with YouTube's own Shorts overlay
# (channel icon/name/subscribe/description), which occupies roughly the
# bottom 300-400px once actually published.
HOOK_BAND_TOP = 230
HOOK_BAND_HEIGHT = 200
FOOTER_BAND_TOP = 1390
FOOTER_BAND_HEIGHT = 130
BAND_OPACITY = 0.92
ACCENT_BAND_COLORS = {
    "red": "0xB71C1C",
    "green": "0x1B6E45",
    "blue": "0x1565A8",
    "gold": "0xA8790A",
}
DEFAULT_ACCENT_BAND_COLOR = ACCENT_BAND_COLORS["gold"]


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int


def run(command: list[str], dry_run: bool = False) -> CommandResult:
    print("$ " + " ".join(command))
    if dry_run:
        return CommandResult(command, 0)
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return CommandResult(command, completed.returncode)


def slug_from_url(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url)
    if match:
        return match.group(1)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", url).strip("-")
    return safe[:80] or "youtube-video"


def seconds(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raw = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid timestamp: {value}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def ass_time(value: str | int | float) -> str:
    total = seconds(value)
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def ass_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def read_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def video_dir(manifest: dict[str, Any], work_dir: Path) -> Path:
    slug = manifest.get("video_id") or slug_from_url(manifest["video_url"])
    return work_dir / slug


def download(manifest: dict[str, Any], work_dir: Path, dry_run: bool) -> Path:
    out_dir = video_dir(manifest, work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = out_dir / "source.mp4"
    command = [
        "yt-dlp",
        "--remote-components",
        "ejs:github",
        "--cookies-from-browser",
        "chrome",
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "--write-auto-subs",
        "--sub-lang",
        "ja",
        "--sub-format",
        "json3",
        "-o",
        str(out_dir / "source.%(ext)s"),
        manifest["video_url"],
    ]
    run(command, dry_run=dry_run)
    return source


def transcript_from_json3(json3_path: Path, out_path: Path) -> None:
    data = json.loads(json3_path.read_text(encoding="utf-8"))
    rows: list[str] = []
    for event in data.get("events", []):
        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        text_parts = []
        for seg in event.get("segs", []):
            utf8 = seg.get("utf8")
            if utf8:
                text_parts.append(utf8)
        text = "".join(text_parts).strip()
        if not text:
            continue
        text = re.sub(r"\s+", " ", text)
        rows.append(f"{start_ms / 1000:.3f}\t{text}")
    out_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def build_transcript(manifest: dict[str, Any], work_dir: Path) -> Path:
    out_dir = video_dir(manifest, work_dir)
    json3_candidates = sorted(out_dir.glob("*.ja*.json3"))
    if not json3_candidates:
        raise SystemExit(f"No Japanese json3 subtitle file found in {out_dir}")
    transcript_path = out_dir / "transcript.tsv"
    transcript_from_json3(json3_candidates[0], transcript_path)
    return transcript_path


def find_json3_path(manifest: dict[str, Any], work_dir: Path) -> Path:
    out_dir = video_dir(manifest, work_dir)
    explicit = manifest.get("subtitle_json3_path")
    if explicit:
        return Path(explicit)
    json3_candidates = sorted(out_dir.glob("*.ja*.json3"))
    if not json3_candidates:
        raise SystemExit(f"No Japanese json3 subtitle file found in {out_dir}")
    return json3_candidates[0]


def load_json3_events(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    events: list[dict[str, Any]] = []
    raw_events = data.get("events", [])
    text_events: list[tuple[int, dict[str, Any], str]] = []
    for index, event in enumerate(raw_events):
        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        text = event_text(event)
        if not text:
            continue
        text_events.append((index, event, text))

    for text_index, (raw_index, event, text) in enumerate(text_events):
        start_ms = event["tStartMs"]
        next_start_ms = None
        for _, next_event, _ in text_events[text_index + 1 :]:
            if next_event["tStartMs"] > start_ms:
                next_start_ms = next_event["tStartMs"]
                break
        duration_ms = event.get("dDurationMs") or 2500
        end_ms = next_start_ms if next_start_ms is not None else start_ms + duration_ms
        if end_ms <= start_ms:
            end_ms = next_event_start_ms(raw_events, raw_index)
        if duration_ms <= 0:
            duration_ms = 2500
        events.append(
            {
                "start": start_ms / 1000,
                "end": end_ms / 1000,
                "text": text,
            }
        )
    return events


def next_event_start_ms(raw_events: list[dict[str, Any]], index: int) -> int:
    current = raw_events[index].get("tStartMs", 0)
    for next_event in raw_events[index + 1 :]:
        next_start = next_event.get("tStartMs")
        if next_start is not None and next_start > current:
            return next_start
    return current + 2500


def event_text(event: dict[str, Any]) -> str:
    parts: list[str] = []
    for segment in event.get("segs", []):
        text = segment.get("utf8")
        if text:
            parts.append(text)
    text = "".join(parts)
    text = text.replace("\n", "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text == "[音楽]":
        return ""
    return text


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    for source, replacement in corrections.items():
        text = text.replace(source, replacement)
    return text


def clip_corrections(manifest: dict[str, Any], clip: dict[str, Any]) -> dict[str, str]:
    corrections: dict[str, str] = {}
    corrections.update(manifest.get("caption_corrections", {}))
    corrections.update(clip.get("caption_corrections", {}))
    return corrections


def caption_source(manifest: dict[str, Any], clip: dict[str, Any]) -> str:
    return str(clip.get("caption_source") or manifest.get("caption_source") or "json3")


def derive_captions_from_json3(
    manifest: dict[str, Any],
    clip: dict[str, Any],
    json3_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    corrections = clip_corrections(manifest, clip)
    captions: list[dict[str, Any]] = []
    output_offset = 0.0
    for segment in clip["segments"]:
        segment_start = seconds(segment["start"])
        segment_end = seconds(segment["end"])
        for event in json3_events:
            start = max(event["start"], segment_start)
            end = min(event["end"], segment_end)
            if end <= start:
                continue
            text = apply_corrections(event["text"], corrections)
            if not text.strip():
                continue
            mapped_start = output_offset + (start - segment_start)
            mapped_end = output_offset + (end - segment_start)
            captions.extend(split_caption(mapped_start, mapped_end, text))
        output_offset += segment_end - segment_start
    return fill_caption_edges_and_gaps(captions, clip_duration(clip))


def split_caption(start: float, end: float, text: str) -> list[dict[str, Any]]:
    chunks = chunk_text(text, MAX_CAPTION_CHUNK_CHARS)
    if not chunks:
        return []
    duration = end - start
    chunk_duration = duration / len(chunks)
    captions: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        chunk_start = start + chunk_duration * index
        chunk_end = end if index == len(chunks) - 1 else start + chunk_duration * (index + 1)
        captions.append(
            {
                "start": chunk_start,
                "end": chunk_end,
                "text": wrap_caption(chunk),
                "accent": False,
            }
        )
    return captions


def chunk_text(text: str, max_chars: int) -> list[str]:
    normalized = re.sub(r"\s+", "", text)
    if not normalized:
        return []
    pieces = [piece for piece in re.split(r"(?<=[。！？、])", normalized) if piece]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if len(piece) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(piece[i : i + max_chars] for i in range(0, len(piece), max_chars))
            continue
        if current and len(current + piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks


def wrap_caption(text: str) -> str:
    if len(text) <= MAX_CAPTION_LINE_CHARS:
        return text
    midpoint = len(text) // 2
    return text[:midpoint] + "\n" + text[midpoint:]


def fill_caption_edges_and_gaps(
    captions: list[dict[str, Any]],
    duration: float,
) -> list[dict[str, Any]]:
    if not captions:
        return captions
    captions = sorted(captions, key=lambda caption: seconds(caption["start"]))
    captions[0]["start"] = 0.0
    previous = captions[0]
    for caption in captions[1:]:
        gap = seconds(caption["start"]) - seconds(previous["end"])
        if gap > 0:
            previous["end"] = caption["start"]
        previous = caption
    captions[-1]["end"] = duration
    return captions


def whisper_dir(out_dir: Path) -> Path:
    return out_dir / "whisper"


def captions_dir(out_dir: Path) -> Path:
    return out_dir / "captions"


def segment_audio_path(out_dir: Path, clip: dict[str, Any], index: int) -> Path:
    return whisper_dir(out_dir) / f"{clip['slug']}_seg{index}.wav"


def words_cache_path(out_dir: Path, clip: dict[str, Any], index: int) -> Path:
    return whisper_dir(out_dir) / f"{clip['slug']}_seg{index}.words.json"


def whisper_caption_draft_path(out_dir: Path, clip: dict[str, Any]) -> Path:
    return captions_dir(out_dir) / f"{clip['slug']}.json"


def extract_segment_audio(
    source: Path,
    segment: dict[str, Any],
    out_path: Path,
    dry_run: bool,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ss",
        str(seconds(segment["start"])),
        "-to",
        str(seconds(segment["end"])),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out_path),
    ]
    run(command, dry_run=dry_run)


def transcribe_words(wav_path: Path, out_path: Path, model_size: str) -> list[dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is required for whisper caption sources. "
            "Install it (e.g. `pip install faster-whisper`) and retry."
        ) from exc

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _ = model.transcribe(str(wav_path), language="ja", word_timestamps=True)
    words: list[dict[str, Any]] = []
    for segment in segments:
        for word in segment.words or []:
            words.append({"start": round(word.start, 2), "end": round(word.end, 2), "word": word.word})
    out_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    return words


def load_or_transcribe_words(
    clip: dict[str, Any],
    index: int,
    segment: dict[str, Any],
    source: Path,
    out_dir: Path,
    dry_run: bool,
    force: bool,
    model_size: str,
) -> list[dict[str, Any]]:
    wav_path = segment_audio_path(out_dir, clip, index)
    words_path = words_cache_path(out_dir, clip, index)
    if force or not wav_path.exists():
        extract_segment_audio(source, segment, wav_path, dry_run)
    if not force and words_path.exists():
        return json.loads(words_path.read_text(encoding="utf-8"))
    if dry_run:
        return []
    return transcribe_words(wav_path, words_path, model_size)


def group_words_into_events(
    words: list[dict[str, Any]],
    max_gap: float = WHISPER_MAX_GAP,
    min_event_chars: int = WHISPER_MIN_EVENT_CHARS,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for word in words:
        text = word["word"]
        if current is None:
            current = {"start": word["start"], "end": word["end"], "text": text}
            continue
        gap = word["start"] - current["end"]
        ends_sentence = current["text"].rstrip().endswith(("。", "、", "！", "？"))
        if gap > max_gap or (ends_sentence and len(current["text"]) >= min_event_chars):
            events.append(current)
            current = {"start": word["start"], "end": word["end"], "text": text}
        else:
            current["end"] = word["end"]
            current["text"] += text
    if current is not None:
        events.append(current)
    return events


def build_whisper_captions(
    manifest: dict[str, Any],
    clip: dict[str, Any],
    source: Path,
    out_dir: Path,
    dry_run: bool,
    force: bool,
    model_size: str,
) -> list[dict[str, Any]]:
    corrections = clip_corrections(manifest, clip)
    captions: list[dict[str, Any]] = []
    output_offset = 0.0
    for index, segment in enumerate(clip["segments"]):
        words = load_or_transcribe_words(clip, index, segment, source, out_dir, dry_run, force, model_size)
        for event in group_words_into_events(words):
            text = apply_corrections(event["text"], corrections)
            if not text.strip():
                continue
            captions.extend(
                split_caption(output_offset + event["start"], output_offset + event["end"], text)
            )
        output_offset += seconds(segment["end"]) - seconds(segment["start"])
    return fill_caption_edges_and_gaps(captions, clip_duration(clip))


def build_char_timeline(
    clip: dict[str, Any],
    source: Path,
    out_dir: Path,
    dry_run: bool,
    force: bool,
    model_size: str,
) -> tuple[str, list[float]]:
    chars: list[str] = []
    times: list[float] = []
    output_offset = 0.0
    for index, segment in enumerate(clip["segments"]):
        words = load_or_transcribe_words(clip, index, segment, source, out_dir, dry_run, force, model_size)
        for word in words:
            text = word["word"]
            if not text:
                continue
            start = output_offset + word["start"]
            end = output_offset + word["end"]
            span = max(end - start, 0.01)
            for i, ch in enumerate(text):
                chars.append(ch)
                times.append(start + span * i / len(text))
        output_offset += seconds(segment["end"]) - seconds(segment["start"])
    return "".join(chars), times


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text)


def align_hand_captions(
    captions: list[dict[str, Any]],
    timeline_text: str,
    timeline_times: list[float],
    duration: float,
) -> list[dict[str, Any]]:
    """Keep the hand-written caption text as-is, but retime each line to when
    that content is actually spoken, found via fuzzy substring matching
    against a whisper word-derived, per-character timeline. This trades
    verbatim ASR text (which can be rough) for the polished hand-written
    text, while still fixing the timing drift that comes from hand-guessed
    timestamps.

    Hand-written captions are often paraphrased, not verbatim, so some lines
    have no reliable match in the transcript. Those are interpolated between
    the nearest confidently-matched neighbors rather than collapsing onto
    whichever caption matched last.
    """
    count = len(captions)
    match_starts: list[float | None] = [None] * count
    match_ends: list[float | None] = [None] * count
    search_from = 0
    for index, caption in enumerate(captions):
        target = normalize_for_match(caption["text"])
        if not target or search_from >= len(timeline_text):
            continue
        matcher = difflib.SequenceMatcher(None, timeline_text[search_from:], target, autojunk=False)
        match = matcher.find_longest_match(0, len(timeline_text) - search_from, 0, len(target))
        if match.size < max(4, len(target) // 2):
            continue
        match_start_index = search_from + match.a
        match_end_index = match_start_index + match.size
        match_starts[index] = timeline_times[match_start_index]
        match_ends[index] = timeline_times[min(match_end_index, len(timeline_times) - 1)]
        search_from = match_end_index

    def caption_weight(index: int) -> int:
        return len(normalize_for_match(captions[index]["text"])) or 1

    def distribute(indices: list[int], start_time: float, end_time: float, starts: list[float]) -> None:
        if not indices:
            return
        total = sum(caption_weight(j) for j in indices)
        acc = 0
        for j in indices:
            fraction = acc / total if total else 0.0
            starts[j] = start_time + (end_time - start_time) * fraction
            acc += caption_weight(j)

    starts: list[float] = [0.0] * count
    anchor_indices = [index for index in range(count) if match_starts[index] is not None]
    if not anchor_indices:
        distribute(list(range(count)), 0.0, duration, starts)
    else:
        distribute(list(range(0, anchor_indices[0])), 0.0, match_starts[anchor_indices[0]], starts)
        for pos in range(len(anchor_indices) - 1):
            left, right = anchor_indices[pos], anchor_indices[pos + 1]
            starts[left] = match_starts[left]
            gap_start = match_ends[left] if match_ends[left] is not None else match_starts[left]
            distribute(list(range(left + 1, right)), gap_start, match_starts[right], starts)
        last = anchor_indices[-1]
        starts[last] = match_starts[last]
        tail_start = match_ends[last] if match_ends[last] is not None else match_starts[last]
        distribute(list(range(last + 1, count)), tail_start, duration, starts)
    for index in range(1, count):
        if starts[index] < starts[index - 1]:
            starts[index] = starts[index - 1]

    aligned: list[dict[str, Any]] = []
    for index, caption in enumerate(captions):
        start = starts[index]
        match_end = match_ends[index]
        end = match_end if match_end is not None and match_end > start else (
            starts[index + 1] if index + 1 < count else duration
        )
        if end <= start:
            end = min(start + 1.0, duration)
        aligned.append(
            {"start": start, "end": end, "text": caption["text"], "accent": bool(caption.get("accent", False))}
        )
    if aligned:
        aligned[0]["start"] = 0.0
        aligned[-1]["end"] = duration
        for index in range(count - 1):
            if aligned[index]["end"] > aligned[index + 1]["start"]:
                aligned[index]["end"] = aligned[index + 1]["start"]
    return aligned


def build_hybrid_captions(
    clip: dict[str, Any],
    source: Path,
    out_dir: Path,
    dry_run: bool,
    force: bool,
    model_size: str,
) -> list[dict[str, Any]]:
    hand_captions = clip.get("captions", [])
    if not hand_captions:
        raise SystemExit(
            f"{clip['slug']}: caption_source 'hybrid' requires a 'captions' array with hand-written text"
        )
    timeline_text, timeline_times = build_char_timeline(clip, source, out_dir, dry_run, force, model_size)
    return align_hand_captions(hand_captions, timeline_text, timeline_times, clip_duration(clip))


def write_whisper_caption_draft(
    manifest: dict[str, Any],
    clip: dict[str, Any],
    source: Path,
    out_dir: Path,
    dry_run: bool,
    force: bool,
    model_size: str,
) -> Path:
    draft_path = whisper_caption_draft_path(out_dir, clip)
    if draft_path.exists() and not force:
        print(f"Skip {clip['slug']}: caption draft already exists at {draft_path} (use --force to regenerate)")
        return draft_path
    if caption_source(manifest, clip) == "hybrid":
        captions = build_hybrid_captions(clip, source, out_dir, dry_run, force, model_size)
    else:
        captions = build_whisper_captions(manifest, clip, source, out_dir, dry_run, force, model_size)
    if dry_run:
        return draft_path
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(json.dumps(captions, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft_path


def load_whisper_captions(out_dir: Path, clip: dict[str, Any]) -> list[dict[str, Any]]:
    draft_path = whisper_caption_draft_path(out_dir, clip)
    if not draft_path.exists():
        raise SystemExit(
            f"No whisper caption draft found for {clip['slug']} at {draft_path}. "
            "Run --step transcribe-whisper first, then review/correct the draft."
        )
    return json.loads(draft_path.read_text(encoding="utf-8"))


def get_captions(
    manifest: dict[str, Any],
    clip: dict[str, Any],
    json3_events: list[dict[str, Any]] | None,
    out_dir: Path,
) -> list[dict[str, Any]]:
    source = caption_source(manifest, clip)
    if source == "manual":
        return clip.get("captions", [])
    if source == "json3":
        if json3_events is None:
            raise SystemExit("json3 captions requested, but no json3 events were loaded")
        return derive_captions_from_json3(manifest, clip, json3_events)
    if source in ("whisper", "hybrid"):
        return load_whisper_captions(out_dir, clip)
    raise SystemExit(f"Unknown caption_source: {source}")


def write_ass(clip: dict[str, Any], captions: list[dict[str, Any]], out_path: Path) -> None:
    duration = clip_duration(clip)
    header = ass_escape(clip.get("header", "FIRE経験者のリアル"))
    hook = ass_escape(clip.get("hook", clip["title"]))
    footer = ass_escape(clip.get("footer", "▼ 本編は下のリンクから"))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Header,Hiragino Sans GB,72,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,2,8,34,34,112,1",
        # Hook/Footer are plain outlined text (no per-glyph box) because the
        # full-width color band behind them is drawn by ffmpeg (drawbox), not ASS.
        "Style: Hook,Hiragino Sans GB,92,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,8,60,60,270,1",
        "Style: Default,Hiragino Sans GB,82,&H00FFFFFF,&H000000FF,&H00000000,&HE0111111,-1,0,0,0,100,100,0,0,3,4,0,2,120,120,560,1",
        "Style: Accent,Hiragino Sans GB,90,&H00FFFFFF,&H000000FF,&H001880A0,&HDD8C7914,-1,0,0,0,100,100,0,0,3,4,0,2,120,120,560,1",
        "Style: Footer,Hiragino Sans GB,50,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,60,60,436,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,0:00:00.00,{ass_time(duration)},Header,,0,0,0,,{header}",
        f"Dialogue: 1,0:00:00.00,{ass_time(duration)},Hook,,0,0,0,,{hook}",
        # Persistent for the whole clip, not just after captions end, so it
        # always reads as a fixed CTA like the reference video.
        f"Dialogue: 1,0:00:00.00,{ass_time(duration)},Footer,,0,0,0,,{footer}",
    ]
    for caption in captions:
        style = "Accent" if caption.get("accent") else "Default"
        text = ass_escape(caption["text"])
        lines.append(
            "Dialogue: 0,"
            f"{ass_time(caption['start'])},{ass_time(caption['end'])},"
            f"{style},,0,0,0,,{text}"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_clip(
    clip: dict[str, Any],
    captions: list[dict[str, Any]],
    allow_gaps: bool = False,
) -> list[str]:
    errors: list[str] = []
    duration = clip_duration(clip)
    if not captions:
        return [f"{clip['slug']}: captions is empty"]

    previous_end = 0.0
    for index, caption in enumerate(captions):
        start = seconds(caption["start"])
        end = seconds(caption["end"])
        label = f"{clip['slug']} captions[{index}]"
        caption_text = str(caption.get("text", ""))
        if start < 0:
            errors.append(f"{label}: start must be >= 0")
        if end <= start:
            errors.append(f"{label}: end must be after start")
        if not caption_text.strip():
            errors.append(f"{label}: text is empty")
        for line in caption_text.splitlines() or [caption_text]:
            if len(line) > MAX_CAPTION_LINE_CHARS:
                errors.append(
                    f"{label}: line is too long for large subtitles "
                    f"({len(line)} chars): {line}"
                )
        # whisper/hybrid captions can legitimately leave gaps where nothing
        # was matched to on-screen text (e.g. unmatched filler speech), so
        # skip the gap check for those sources.
        if not allow_gaps and start - previous_end > CAPTION_GAP_TOLERANCE:
            errors.append(
                f"{label}: caption gap {start - previous_end:.2f}s "
                f"from {previous_end:.2f}s to {start:.2f}s"
            )
        if previous_end - start > CAPTION_GAP_TOLERANCE:
            errors.append(
                f"{label}: overlaps previous caption by {previous_end - start:.2f}s"
            )
        previous_end = max(previous_end, end)

    if captions:
        first_start = seconds(captions[0]["start"])
        last_end = seconds(captions[-1]["end"])
        if first_start > CAPTION_EDGE_TOLERANCE:
            errors.append(f"{clip['slug']}: first caption starts at {first_start:.2f}s")
        if duration - last_end > CAPTION_EDGE_TOLERANCE:
            errors.append(
                f"{clip['slug']}: captions end at {last_end:.2f}s, "
                f"but clip duration is {duration:.2f}s"
            )
        if last_end - duration > CAPTION_EDGE_TOLERANCE:
            errors.append(
                f"{clip['slug']}: captions end at {last_end:.2f}s, "
                f"after clip duration {duration:.2f}s"
            )

    return errors


def validate_manifest(
    manifest: dict[str, Any],
    out_dir: Path,
    json3_events: list[dict[str, Any]] | None = None,
) -> None:
    errors: list[str] = []
    for clip in manifest.get("clips", []):
        captions = get_captions(manifest, clip, json3_events, out_dir)
        allow_gaps = caption_source(manifest, clip) in ("whisper", "hybrid")
        errors.extend(validate_clip(clip, captions, allow_gaps=allow_gaps))
    if errors:
        joined = "\n".join(f"- {error}" for error in errors)
        raise SystemExit(f"Manifest validation failed:\n{joined}")


def clip_duration(clip: dict[str, Any]) -> float:
    if "duration" in clip:
        return seconds(clip["duration"])
    return sum(seconds(segment["end"]) - seconds(segment["start"]) for segment in clip["segments"])


def ffmpeg_filter(clip: dict[str, Any], ass_path: Path) -> tuple[str, list[str]]:
    parts: list[str] = []
    concat_refs: list[str] = []
    for index, segment in enumerate(clip["segments"]):
        start = seconds(segment["start"])
        end = seconds(segment["end"])
        parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]")
        parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]")
        concat_refs.append(f"[v{index}][a{index}]")
    parts.append("".join(concat_refs) + f"concat=n={len(concat_refs)}:v=1:a=1[vcat][acat]")
    escaped_ass = str(ass_path).replace("'", r"'\''")
    band_color = ACCENT_BAND_COLORS.get(clip.get("accent", "gold"), DEFAULT_ACCENT_BAND_COLOR)
    parts.append(
        "[vcat]scale=1080:-2:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:500:color=0x101010,"
        f"drawbox=x=0:y={HOOK_BAND_TOP}:w=1080:h={HOOK_BAND_HEIGHT}:color={band_color}@{BAND_OPACITY}:t=fill,"
        f"drawbox=x=0:y={FOOTER_BAND_TOP}:w=1080:h={FOOTER_BAND_HEIGHT}:color={band_color}@{BAND_OPACITY}:t=fill,"
        f"fps=30,subtitles='{escaped_ass}'[vout]"
    )
    return ";".join(parts), ["[vout]", "[acat]"]


def render(manifest: dict[str, Any], manifest_path: Path, work_dir: Path, dry_run: bool) -> list[Path]:
    out_dir = video_dir(manifest, work_dir)
    outputs_dir = out_dir / "outputs"
    subtitles_dir = outputs_dir / "subtitles"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    source = Path(manifest.get("source_path") or out_dir / "source.mp4")
    if not source.exists() and not dry_run:
        raise SystemExit(f"Source video not found: {source}")
    json3_events = None
    if any(caption_source(manifest, clip) == "json3" for clip in manifest.get("clips", [])):
        json3_events = load_json3_events(find_json3_path(manifest, work_dir))
    validate_manifest(manifest, out_dir, json3_events)

    rendered: list[Path] = []
    for clip in manifest["clips"]:
        slug = clip["slug"]
        ass_path = subtitles_dir / f"{slug}.ass"
        out_path = outputs_dir / f"{slug}.mp4"
        captions = get_captions(manifest, clip, json3_events, out_dir)
        write_ass(clip, captions, ass_path)
        filter_graph, maps = ffmpeg_filter(clip, ass_path)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            filter_graph,
            "-map",
            maps[0],
            "-map",
            maps[1],
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        run(command, dry_run=dry_run)
        rendered.append(out_path)
    write_summary(manifest, manifest_path, rendered, outputs_dir)
    return rendered


def write_summary(
    manifest: dict[str, Any],
    manifest_path: Path,
    rendered: list[Path],
    outputs_dir: Path,
) -> None:
    rows = [
        f"# {manifest.get('title', 'Fire Lab Shorts')} outputs",
        "",
        f"Manifest: `{manifest_path}`",
        f"Video: {manifest['video_url']}",
        "",
    ]
    for clip, output in zip(manifest["clips"], rendered):
        rows.append(f"- {clip['title']}: `{output}`")
    (outputs_dir / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON manifest with clips")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help=f"Working directory, default: {DEFAULT_WORK_DIR}",
    )
    parser.add_argument(
        "--step",
        choices=["download", "transcript", "transcribe-whisper", "validate", "render", "all"],
        default="render",
        help="Pipeline step to run",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate cached whisper audio/words/caption drafts instead of reusing them",
    )
    parser.add_argument(
        "--whisper-model",
        default=DEFAULT_WHISPER_MODEL,
        help=f"faster-whisper model size, default: {DEFAULT_WHISPER_MODEL}",
    )
    args = parser.parse_args()

    manifest = read_manifest(args.manifest)
    out_dir = video_dir(manifest, args.work_dir)
    if args.step in ("download", "all"):
        download(manifest, args.work_dir, args.dry_run)
    if args.step in ("transcript", "all"):
        path = build_transcript(manifest, args.work_dir)
        print(f"Wrote {path}")
    if args.step == "transcribe-whisper":
        source = Path(manifest.get("source_path") or out_dir / "source.mp4")
        for clip in manifest.get("clips", []):
            if caption_source(manifest, clip) not in ("whisper", "hybrid"):
                continue
            draft_path = write_whisper_caption_draft(
                manifest, clip, source, out_dir, args.dry_run, args.force, args.whisper_model
            )
            print(f"Wrote {draft_path}")
    if args.step == "validate":
        json3_events = None
        if any(caption_source(manifest, clip) == "json3" for clip in manifest.get("clips", [])):
            json3_events = load_json3_events(find_json3_path(manifest, args.work_dir))
        validate_manifest(manifest, out_dir, json3_events)
        print("Manifest validation passed")
    if args.step in ("render", "all"):
        rendered = render(manifest, args.manifest, args.work_dir, args.dry_run)
        for path in rendered:
            print(f"Wrote {path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
