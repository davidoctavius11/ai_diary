"""
parse_translate_diary.py
------------------------
Parses Brian's 2025 handwritten diary (Chinese, messy date headers, OCR artifacts)
and translates each dated entry to English using DeepSeek (via OpenAI-compatible API).

Context:
  - "I" (我) = Brian's dad, the narrator
  - "you" (你) = Brian (白小白, also Brian, age 5→6 in 2025)

Output: data/fusion/diary_parsed.json

Usage:
    python scripts/parse_translate_diary.py
"""

import json
import hashlib
import os
import re
import time
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DIARY_FILE = BASE_DIR / "data" / "diary" / "brian_diary_2025.txt"
OUTPUT_FILE = BASE_DIR / "data" / "fusion" / "diary_parsed.json"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
)


def make_id(content: str, date: str) -> str:
    return hashlib.md5(f"{date}{content[:80]}".encode()).hexdigest()[:12]


def preprocess(text: str) -> str:
    """Fix known OCR / typo artifacts in the date headers."""
    fixes = [
        # Thai characters before "25.8.19"
        (r'หา5\.\s*8\.19', '2025.8.19'),
        # "20252.9" → "2025.2.9"
        (r'20252\.9', '2025.2.9'),
        # "2025.830" → "2025.8.30"
        (r'2025\.830\b', '2025.8.30'),
        # "202510 1" → "2025.10.1"
        (r'202510\s+1\b', '2025.10.1'),
        # "2025.9.2/" ambiguous slash → Sept 21
        (r'2025\.9\.2/', '2025.9.21'),
        # "2025.1925" → "2025.10.25"
        (r'2025\.1925\b', '2025.10.25'),
        # "20.25.10" → "2025.10"
        (r'20\.25\.10', '2025.10'),
        # "25:8.18" or "2025:8.18" colon as dot
        (r'2025:8\.', '2025.8.'),
        (r'2025:9\.', '2025.9.'),
        (r'2025:11\.', '2025.11.'),
        (r'2025:12\.', '2025.12.'),
        (r'2025-7\.', '2025.7.'),
        (r'2025- 12\.', '2025.12.'),
        (r'2025:10\.', '2025.10.'),
    ]
    for pattern, replacement in fixes:
        text = re.sub(pattern, replacement, text)
    return text


def extract_date(line: str) -> str | None:
    """Return ISO date if line looks like a date header; else None."""
    s = line.strip()
    if not s or len(s) > 50:
        return None

    # Remove leading non-digit/non-ASCII-digit noise
    s = re.sub(r'^[^\d]+', '', s).strip()
    if not s:
        return None

    nums = re.findall(r'\d+', s)
    if len(nums) < 2:
        return None

    year = month = day = None
    i = 0

    while i < len(nums):
        n = nums[i]
        if n == '2025':
            year = 2025; i += 1; break
        elif n == '25':
            year = 2025; i += 1; break
        elif n == '20' and i + 1 < len(nums) and nums[i + 1] == '25':
            year = 2025; i += 2; break
        elif len(n) >= 5 and n.startswith('2025'):
            year = 2025
            extra = n[4:]
            nums = nums[:i] + ([extra] if extra else []) + nums[i + 1:]
            i += 1; break
        i += 1

    if year is None:
        return None

    remaining = nums[i:]
    if len(remaining) >= 2:
        try:
            m, d = int(remaining[0]), int(remaining[1])
            if 1 <= m <= 12 and 1 <= d <= 31:
                month, day = m, d
        except (ValueError, IndexError):
            pass
    elif len(remaining) == 1:
        # "2025.830" style merged month+day (already fixed in preprocess, but keep)
        n = remaining[0]
        try:
            if len(n) == 3:
                m, d = int(n[0]), int(n[1:])
            elif len(n) == 4:
                m, d = int(n[:2]), int(n[2:])
            else:
                m = d = 0
            if 1 <= m <= 12 and 1 <= d <= 31:
                month, day = m, d
        except ValueError:
            pass

    if year and month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def split_entries(text: str) -> list[tuple[str, str]]:
    """Split diary text into (date, content) pairs."""
    entries: list[tuple[str, str]] = []
    lines = text.split('\n')
    current_date = None
    current_lines: list[str] = []

    for line in lines:
        date = extract_date(line)
        if date:
            if current_date and current_lines:
                content = '\n'.join(current_lines).strip()
                if content:
                    entries.append((current_date, content))
            current_date = date
            current_lines = []
        elif current_date is not None:
            current_lines.append(line)

    if current_date and current_lines:
        content = '\n'.join(current_lines).strip()
        if content:
            entries.append((current_date, content))

    return entries


TRANSLATE_PROMPT = """\
Translate the following Chinese diary entry to English.

CONTEXT (read carefully):
- Written by a Chinese father TO his son Brian (Chinese name: 白小白)
- "I" = the father/dad (narrator and writer)
- "you" = Brian, his son, age 5–6 in 2025
- 又白 or 弟弟 = Brian's younger brother
- 姥姥 = Brian's maternal grandma  |  姥爷 = maternal grandpa
- 爽宁/妈妈 = Brian's mom  |  爷爷/奶奶 = paternal grandparents
- Tone: warm, reflective, loving, sometimes philosophical

INSTRUCTIONS:
- Translate naturally — preserve the father's voice and warmth
- Keep Chinese family terms in parenthetical pinyin on first use, e.g. "Grandma (姥姥)"
- Fix obvious OCR garble using context; mark truly unreadable parts as [unclear]
- Do NOT add commentary, headers, or notes — just the translation

ENTRY:
{text}"""


def translate(chinese: str) -> str:
    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=2048,
        messages=[{"role": "user", "content": TRANSLATE_PROMPT.format(text=chinese)}],
    )
    return resp.choices[0].message.content.strip()


def main():
    if not DIARY_FILE.exists():
        print(f"✗ Diary file not found: {DIARY_FILE}")
        print("  Save the diary text to data/diary/brian_diary_2025.txt first.")
        return

    print(f"Reading {DIARY_FILE.name} ...")
    raw = DIARY_FILE.read_text(encoding="utf-8")
    text = preprocess(raw)

    entries = split_entries(text)
    print(f"Found {len(entries)} dated entries")
    for date, _ in entries[:5]:
        print(f"  • {date}")
    if len(entries) > 5:
        print(f"  ... and {len(entries) - 5} more")

    results = []
    print(f"\nTranslating with DeepSeek ...")
    for date, chinese in tqdm(entries, desc="Translating"):
        try:
            english = translate(chinese)
            # Bilingual content: both languages embedded together so Brian can
            # query in either Chinese or English and get a match.
            bilingual = f"{english}\n\n[中文原文]\n{chinese}"
            entry = {
                "id": make_id(bilingual, date),
                "date": date,
                "content": bilingual,      # embedded (both languages)
                "content_en": english,     # English-only (used by chatbot for display)
                "content_zh": chinese,     # Chinese-only (for reference)
                "source": "brian_diary_2025.txt",
                "type": "diary",
            }
        except Exception as exc:
            print(f"\n  ✗ Error on {date}: {exc} — keeping Chinese only")
            entry = {
                "id": make_id(chinese, date),
                "date": date,
                "content": chinese,
                "content_zh": chinese,
                "source": "brian_diary_2025.txt",
                "type": "diary",
            }
        results.append(entry)
        time.sleep(0.15)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✓ {len(results)} entries → {OUTPUT_FILE}")
    dates = [r["date"] for r in results]
    if dates:
        print(f"  Date range: {min(dates)} → {max(dates)}")


if __name__ == "__main__":
    main()
