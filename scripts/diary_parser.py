"""
diary_parser.py
---------------
Parses diary entries from multiple formats found in data/diary/:
  - Flomo JSON export  (*.json with "items" key)
  - Notion Markdown    (*.md files with YAML frontmatter)
  - Plain text         (*.txt files)
  - Scanned images     (*.jpg/*.png — OCR via Tesseract if installed)

All entries are normalized to: {id, date, content, source, type}
Output saved to data/fusion/diary_parsed.json

Usage:
    python scripts/diary_parser.py
"""

import os
import json
import hashlib
import re
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DIARY_DIR = BASE_DIR / "data" / "diary"
OUTPUT_FILE = BASE_DIR / "data" / "fusion" / "diary_parsed.json"

# Try to import optional OCR library
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def make_id(content: str, date: str) -> str:
    return hashlib.md5(f"{date}{content[:80]}".encode()).hexdigest()[:12]


def normalize_date(raw: str) -> str:
    """Try to parse various date formats into YYYY-MM-DD."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y/%m/%d",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue
    return raw.strip()


# ---------------------------------------------------------------------------
# Parsers for each format
# ---------------------------------------------------------------------------

def parse_flomo_json(file_path: Path) -> list[dict]:
    """Parse a Flomo JSON export file."""
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    entries = []
    for item in items:
        content = item.get("content", "").strip()
        if not content:
            continue
        date = normalize_date(item.get("created_at", item.get("date", "unknown")))
        tags = item.get("tags", [])
        tag_str = " ".join(f"#{t}" for t in tags) if tags else ""
        full_content = f"{content}\n{tag_str}".strip()

        entries.append({
            "id": make_id(full_content, date),
            "date": date,
            "content": full_content,
            "source": file_path.name,
            "type": "diary",
        })
    return entries


def parse_notion_markdown(file_path: Path) -> list[dict]:
    """Parse a Notion-exported Markdown file (with optional YAML frontmatter)."""
    text = file_path.read_text(encoding="utf-8")

    # Extract YAML frontmatter
    date = "unknown"
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if frontmatter_match:
        fm = frontmatter_match.group(1)
        date_match = re.search(r"date:\s*(.+)", fm)
        if date_match:
            date = normalize_date(date_match.group(1))
        text = text[frontmatter_match.end():]

    # Fall back to guessing date from filename
    if date == "unknown":
        date_match = re.search(r"(\d{4}[-_]\d{2}[-_]\d{2})", file_path.name)
        if date_match:
            date = date_match.group(1).replace("_", "-")

    content = text.strip()
    if not content:
        return []

    return [{
        "id": make_id(content, date),
        "date": date,
        "content": content,
        "source": file_path.name,
        "type": "diary",
    }]


def parse_plain_text(file_path: Path) -> list[dict]:
    """Parse a plain text diary file."""
    content = file_path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    date_match = re.search(r"(\d{4}[-_]\d{2}[-_]\d{2})", file_path.name)
    date = date_match.group(1).replace("_", "-") if date_match else "unknown"

    # Check if content itself starts with a date line
    first_line = content.split("\n")[0]
    if re.match(r"\d{4}[-/]\d{2}[-/]\d{2}", first_line):
        date = normalize_date(first_line)
        content = "\n".join(content.split("\n")[1:]).strip()

    return [{
        "id": make_id(content, date),
        "date": date,
        "content": content,
        "source": file_path.name,
        "type": "diary",
    }]


def parse_scanned_image(file_path: Path) -> list[dict]:
    """OCR a scanned diary image using Tesseract."""
    if not OCR_AVAILABLE:
        print(f"  ⚠ Skipping {file_path.name} — pytesseract not installed.")
        print("    Install with: pip install pytesseract && brew install tesseract")
        return []

    img = Image.open(file_path)
    # Try Chinese + English OCR
    try:
        content = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except pytesseract.TesseractError:
        content = pytesseract.image_to_string(img)

    content = content.strip()
    if not content:
        return []

    date_match = re.search(r"(\d{4}[-_]\d{2}[-_]\d{2})", file_path.name)
    date = date_match.group(1).replace("_", "-") if date_match else "unknown"

    return [{
        "id": make_id(content, date),
        "date": date,
        "content": f"[Scanned diary page]\n{content}",
        "source": file_path.name,
        "type": "diary",
    }]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

def process_file(file_path: Path) -> list[dict]:
    ext = file_path.suffix.lower()
    try:
        if ext == ".json":
            with open(file_path) as f:
                data = json.load(f)
            # Detect Flomo format
            if isinstance(data, dict) and "items" in data:
                return parse_flomo_json(file_path)
            if isinstance(data, list):
                return parse_flomo_json(file_path)
            return []
        elif ext == ".md":
            return parse_notion_markdown(file_path)
        elif ext == ".txt":
            return parse_plain_text(file_path)
        elif ext in IMAGE_EXTENSIONS:
            return parse_scanned_image(file_path)
    except Exception as e:
        print(f"  ✗ Error parsing {file_path.name}: {e}")
    return []


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    diary_files = [
        p for p in DIARY_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".json", ".md", ".txt"} | IMAGE_EXTENSIONS
    ]

    if not diary_files:
        print(f"No diary files found in {DIARY_DIR}")
        print("Add exports from Flomo (.json), Notion (.md), plain text (.txt),")
        print("or scanned images (.jpg/.png) to data/diary/ and re-run.")
        return

    print(f"Found {len(diary_files)} diary files to parse...")

    all_entries = []
    seen_ids = set()

    for file_path in tqdm(diary_files, desc="Parsing diary files"):
        entries = process_file(file_path)
        for entry in entries:
            if entry["id"] not in seen_ids:
                all_entries.append(entry)
                seen_ids.add(entry["id"])

    # Sort chronologically
    all_entries.sort(key=lambda e: e["date"])

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    print(f"\nParsed {len(all_entries)} diary entries → {OUTPUT_FILE}")
    if all_entries:
        dates = [e["date"] for e in all_entries if e["date"] != "unknown"]
        if dates:
            print(f"Date range: {min(dates)} → {max(dates)}")


if __name__ == "__main__":
    main()
