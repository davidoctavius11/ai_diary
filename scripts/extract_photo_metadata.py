"""
extract_photo_metadata.py
--------------------------
Reads person names (face recognition) and GPS location from Mac Photos library
for every photo already synced to data/photos/.

Saves to: data/photos/photo_metadata.json
Used by: photo_analyzer.py to enrich AI descriptions with real names + places.

Usage:
    python scripts/extract_photo_metadata.py
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
PHOTOS_DIR = BASE_DIR / "data" / "photos"
METADATA_FILE = PHOTOS_DIR / "photo_metadata.json"


def open_db():
    try:
        import osxphotos
    except ImportError:
        print("osxphotos not installed. Run: pip install osxphotos")
        sys.exit(1)
    print("Opening Photos library (may take a moment)...")
    return osxphotos.PhotosDB()


def format_location(photo) -> str | None:
    """Return a human-readable place string from photo GPS data."""
    try:
        place = photo.place
        if not place:
            return None
        parts = []
        names = place.names
        for attr in ("city", "state", "country"):
            val = getattr(names, attr, None)
            if val:
                parts.append(val[0] if isinstance(val, list) else val)
        return "，".join(parts) if parts else None
    except Exception:
        return None


def build_uuid_index(db) -> dict[str, object]:
    """Index all Photos library photos by their first 8 UUID chars (uppercase)."""
    index = {}
    print("  Building UUID index from Photos library...")
    for photo in db.photos():
        uuid8 = photo.uuid[:8].upper()
        index[uuid8] = photo
    print(f"  Indexed {len(index)} photos")
    return index


def main():
    if not PHOTOS_DIR.exists():
        print(f"Photos directory not found: {PHOTOS_DIR}")
        return

    db = open_db()
    uuid_index = build_uuid_index(db)

    photo_files = [
        f for f in PHOTOS_DIR.iterdir()
        if f.is_file() and not f.name.startswith(".")
        and f.name != "photo_metadata.json"
    ]
    print(f"Extracting metadata for {len(photo_files)} synced photos...")

    metadata = {}
    found = not_found = 0

    for photo_file in photo_files:
        # UUID8 is the last underscore-separated segment of the stem
        stem = photo_file.stem
        parts = stem.rsplit("_", 1)
        if len(parts) < 2:
            not_found += 1
            continue

        uuid8 = parts[-1].upper()
        photo = uuid_index.get(uuid8)
        if not photo:
            not_found += 1
            continue

        persons = [p for p in (photo.persons or []) if p and p != "_UNKNOWN_"]
        location = format_location(photo)

        metadata[photo_file.name] = {
            "persons": persons,
            "location": location,
        }
        found += 1

    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    has_persons = sum(1 for m in metadata.values() if m["persons"])
    has_location = sum(1 for m in metadata.values() if m["location"])

    print(f"\nDone! Metadata saved to: {METADATA_FILE}")
    print(f"  Matched:       {found}/{len(photo_files)} photos")
    print(f"  With people:   {has_persons}")
    print(f"  With location: {has_location}")
    if not_found:
        print(f"  Not matched:   {not_found} (photos not found in library — iCloud only?)")


if __name__ == "__main__":
    main()
