"""
cross_fuse.py
-------------
Fuses diary entries with nearby photos (±1 day) into richer combined memories.

When a diary entry and one or more photos share the same date (or are within
a day of each other), this script asks DeepSeek to weave them into a single
narrative — the diary provides emotional context and story; the photos provide
specific visual details (location, faces, scene).

Output: data/fusion/fused_memories.json
        (also merged into memories.json by fusion_engine.py)

Usage:
    python scripts/cross_fuse.py           # fuse all matched pairs
    python scripts/cross_fuse.py --dry-run # preview matches without calling API
"""

import argparse
import hashlib
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
MEMORIES_FILE   = BASE_DIR / "data" / "fusion" / "memories.json"
OUTPUT_FILE     = BASE_DIR / "data" / "fusion" / "fused_memories.json"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
)

WINDOW_DAYS = 1   # match photos within ±1 day of diary date

FUSE_PROMPT = """\
You are writing a memory for Brian (白小白), a Chinese boy born in 2019.
His father wrote the diary entries; the photo descriptions come from AI vision analysis.

FAMILY:
- "I" / 爸爸 = father (narrator)
- 妈妈 / 爽宁 = mother
- 弟弟 / 又白 = younger brother
- 姐姐一诺 = elder sister
- 姥姥/姥爷 = maternal grandparents  |  奶奶/爷爷 = paternal grandparents

TASK:
Combine the diary entry and photo description(s) into ONE rich Chinese narrative.
- Use the diary as the emotional and story backbone
- Weave in specific visual details from the photos (place names, who was there, what was happening)
- Write in warm, vivid Chinese — as if dad is telling Brian the story years later
- Do NOT repeat information; blend naturally
- Keep it concise: 150–250 Chinese characters
- Output ONLY the narrative, no headers or labels

DATE: {date}

DIARY ENTRY:
{diary_zh}

PHOTO DESCRIPTION(S):
{photo_descriptions}
"""


def load_memories():
    with open(MEMORIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def group_matches(memories: list[dict]) -> list[dict]:
    """
    For each diary entry, collect photos within ±WINDOW_DAYS.
    Returns list of {diary, photos, date} dicts.
    """
    diary_entries = [m for m in memories if m["type"] == "diary"]
    photos        = [m for m in memories if m["type"] == "photo"
                     and m.get("date", "unknown") != "unknown date"]

    photo_by_date: dict[str, list] = {}
    for p in photos:
        photo_by_date.setdefault(p["date"], []).append(p)

    groups = []
    for entry in diary_entries:
        try:
            d = date.fromisoformat(entry["date"])
        except ValueError:
            continue

        nearby_photos = []
        for delta in range(-WINDOW_DAYS, WINDOW_DAYS + 1):
            day_str = str(d + timedelta(days=delta))
            nearby_photos.extend(photo_by_date.get(day_str, []))

        if nearby_photos:
            groups.append({
                "date":   entry["date"],
                "diary":  entry,
                "photos": nearby_photos,
            })

    return sorted(groups, key=lambda g: g["date"])


def fuse(group: dict) -> str:
    diary_zh = group["diary"].get("content_zh") or group["diary"].get("content", "")
    photo_descs = "\n\n".join(
        f"[照片 {p['date']}] {p['content']}"
        for p in group["photos"]
    )
    prompt = FUSE_PROMPT.format(
        date=group["date"],
        diary_zh=diary_zh,
        photo_descriptions=photo_descs,
    )
    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def make_id(date: str, content: str) -> str:
    return hashlib.md5(f"fused:{date}:{content[:60]}".encode()).hexdigest()[:12]


def load_existing() -> dict[str, dict]:
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            items = json.load(f)
        return {item["date"]: item for item in items}
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview matches without calling API")
    parser.add_argument("--rerun", action="store_true",
                        help="Re-fuse already processed dates")
    args = parser.parse_args()

    memories = load_memories()
    groups   = group_matches(memories)
    existing = load_existing()

    print(f"Found {len(groups)} diary entries with nearby photos")
    print(f"Already fused: {len(existing)}")

    if args.dry_run:
        print("\nMatches (dry run):")
        for g in groups:
            photo_dates = [p['date'] for p in g['photos']]
            print(f"  diary {g['date']} ↔ {len(g['photos'])} photo(s) {photo_dates}")
        return

    to_process = groups if args.rerun else [g for g in groups if g["date"] not in existing]
    print(f"To fuse: {len(to_process)}\n")

    if not to_process:
        print("Nothing new to fuse. Use --rerun to redo all.")
        return

    results = dict(existing) if not args.rerun else {}

    for group in tqdm(to_process, desc="Fusing"):
        try:
            narrative = fuse(group)
            entry = {
                "id":           make_id(group["date"], narrative),
                "date":         group["date"],
                "type":         "fused",
                "source":       "diary+photos",
                "content":      narrative,
                "diary_date":   group["diary"]["date"],
                "photo_dates":  [p["date"] for p in group["photos"]],
                "photo_count":  len(group["photos"]),
            }
            results[group["date"]] = entry
            print(f"\n  ✓ {group['date']} ({len(group['photos'])} photo(s))")
            print(f"    {narrative[:80]}...")
        except Exception as e:
            print(f"\n  ✗ {group['date']}: {e}")
        time.sleep(0.2)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(list(results.values()), f, ensure_ascii=False, indent=2)

    print(f"\n✓ {len(results)} fused memories → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
