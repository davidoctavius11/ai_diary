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


SOUTHERN_HEMISPHERE_COUNTRIES = {
    "澳大利亚", "新西兰", "巴西", "阿根廷", "南非", "智利", "秘鲁",
    "Australia", "New Zealand", "Brazil", "Argentina", "South Africa",
    "Chile", "Peru", "Bolivia", "Paraguay", "Uruguay",
}


def get_season(photo) -> str | None:
    """Derive season from photo date and hemisphere."""
    try:
        month = photo.date.month
        country_vals = getattr(photo.place.names, "country", None) or []
        country = country_vals[0] if isinstance(country_vals, list) and country_vals else str(country_vals)
        southern = any(c in SOUTHERN_HEMISPHERE_COUNTRIES for c in (country_vals if isinstance(country_vals, list) else [country]))
        # Northern hemisphere seasons
        seasons_n = {12: "冬季", 1: "冬季", 2: "冬季",
                     3: "春季", 4: "春季", 5: "春季",
                     6: "夏季", 7: "夏季", 8: "夏季",
                     9: "秋季", 10: "秋季", 11: "秋季"}
        seasons_s = {12: "夏季", 1: "夏季", 2: "夏季",
                     3: "秋季", 4: "秋季", 5: "秋季",
                     6: "冬季", 7: "冬季", 8: "冬季",
                     9: "春季", 10: "春季", 11: "春季"}
        return (seasons_s if southern else seasons_n)[month]
    except Exception:
        return None


def first(val) -> str | None:
    """Return first element if list, else the value itself."""
    if isinstance(val, list):
        return val[0] if val else None
    return val or None


def format_location(photo) -> dict | None:
    """Return structured location dict with full hierarchy from iPhoto place data."""
    try:
        place = photo.place
        if not place:
            return None
        n = place.names

        poi = first(getattr(n, "point_of_interest", None)) or \
              first(getattr(n, "area_of_interest", None))
        sub_locality  = first(getattr(n, "sub_locality", None))
        district      = first(getattr(n, "sub_administrative_area", None))
        city          = first(getattr(n, "city", None))
        state         = first(getattr(n, "state_province", None))
        country       = first(getattr(n, "country", None))

        # Full string: most specific → least specific, deduplicated
        parts = []
        seen = set()
        for p in [poi, sub_locality, district, city, state, country]:
            if p and p not in seen:
                parts.append(p)
                seen.add(p)

        if not parts:
            return None

        return {
            "full":     "，".join(parts),
            "poi":      poi,
            "district": district or city,
            "city":     city,
            "country":  country,
        }
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
        loc = format_location(photo)
        season = get_season(photo) if loc else None

        metadata[photo_file.name] = {
            "persons":  persons,
            "location": loc["full"] if loc else None,
            "location_detail": loc,
            "season":   season,
        }
        found += 1

    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    has_persons  = sum(1 for m in metadata.values() if m["persons"])
    has_location = sum(1 for m in metadata.values() if m["location"])
    has_poi      = sum(1 for m in metadata.values() if m.get("location_detail") and m["location_detail"].get("poi"))
    has_season   = sum(1 for m in metadata.values() if m.get("season"))

    print(f"\nDone! Metadata saved to: {METADATA_FILE}")
    print(f"  Matched:          {found}/{len(photo_files)} photos")
    print(f"  With people:      {has_persons}")
    print(f"  With location:    {has_location}")
    print(f"  With POI name:    {has_poi}")
    print(f"  With season:      {has_season}")
    if not_found:
        print(f"  Not matched:      {not_found} (photos not found in library — iCloud only?)")


if __name__ == "__main__":
    main()
