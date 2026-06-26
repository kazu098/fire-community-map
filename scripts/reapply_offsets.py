#!/usr/bin/env python3
"""Re-apply display offsets to existing normalized JSON without re-fetching Google Sheets."""

import json
import math
from pathlib import Path

GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))


def apply_display_offsets(rows: list[dict]) -> None:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        lat = row.get("lat")
        lng = row.get("lng")
        if lat is None or lng is None:
            row["map_lat"] = None
            row["map_lng"] = None
            row["coordinate_group_key"] = None
            row["coordinate_group_index"] = None
            row["coordinate_group_size"] = 0
            continue
        key = f"{float(lat):.5f},{float(lng):.5f}"
        groups.setdefault(key, []).append(row)

    for key, group in groups.items():
        group.sort(key=lambda r: (r["nickname"], r["sheet_row"]))
        size = len(group)
        for index, row in enumerate(group):
            row["coordinate_group_key"] = key
            row["coordinate_group_index"] = index
            row["coordinate_group_size"] = size
            if size == 1:
                row["map_lat"] = row["lat"]
                row["map_lng"] = row["lng"]
                continue

            lat = float(row["lat"])
            lng = float(row["lng"])
            level = row.get("location_level", "unknown")

            if level == "prefecture":
                max_radius_km = 20.0
            elif level in ("area", "region", "multi_region"):
                max_radius_km = 10.0
            else:
                max_radius_km = 2.0

            r = max_radius_km * math.sqrt((index + 0.5) / size)
            angle = GOLDEN_ANGLE * index
            row["map_lat"] = round(lat + (r / 111.0) * math.sin(angle), 6)
            row["map_lng"] = round(
                lng + (r / (111.0 * max(math.cos(math.radians(lat)), 0.2))) * math.cos(angle),
                6,
            )


def main() -> None:
    src = Path("tmp/member_locations_normalized.json")
    data = json.loads(src.read_text())
    members = data["members"]

    apply_display_offsets(members)

    data["members"] = members
    src.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"オフセット再適用完了: {len(members)} 件 → {src}")


if __name__ == "__main__":
    main()
