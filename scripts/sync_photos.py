"""
sync_photos.py
--------------
Syncs photos from Mac Photos library into data/photos/ by:
  1. Person/face recognition (People album) — e.g. 白小白
  2. Named albums — e.g. "This is us"

Copies files with date-prefixed names. Already-synced photos are skipped.

Prerequisites:
  - Photos app has named faces in the People album
  - .env contains KIDS_PEOPLE and/or KIDS_ALBUMS

Usage:
    python scripts/sync_photos.py              # sync everything
    python scripts/sync_photos.py --dry-run    # preview without copying
    python scripts/sync_photos.py --list-people  # show all recognized people
    python scripts/sync_photos.py --list-albums  # show all album names
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
PHOTOS_DIR = BASE_DIR / "data" / "photos"

KIDS_PEOPLE = [n.strip() for n in os.getenv("KIDS_PEOPLE", "").split(",") if n.strip()]
KIDS_ALBUMS = [n.strip() for n in os.getenv("KIDS_ALBUMS", "").split(",") if n.strip()]

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".tiff"}


def open_db():
    try:
        import osxphotos
    except ImportError:
        print("osxphotos not installed. Run: pip install osxphotos")
        sys.exit(1)
    print("Opening Photos library (may take a moment)...")
    try:
        return osxphotos.PhotosDB()
    except Exception as e:
        print(f"Error opening Photos library: {e}")
        sys.exit(1)


def list_people(db):
    persons = db.persons_as_dict  # {name: count_or_list}
    people = sorted(persons.keys())
    print(f"\nRecognized people in your Photos library ({len(people)}):")
    for p in people:
        val = persons[p]
        count = val if isinstance(val, int) else len(val)
        print(f"  {p}  ({count} photos)")


def list_albums(db):
    # Regular albums
    regular = sorted(db.albums_as_dict.keys())
    # Shared albums (iCloud shared)
    shared = sorted(db.albums_shared_as_dict.keys()) if hasattr(db, "albums_shared_as_dict") else []

    print(f"\nRegular albums ({len(regular)}):")
    for a in regular:
        print(f"  {a}")

    if shared:
        print(f"\nShared albums ({len(shared)}):")
        for a in shared:
            print(f"  [shared] {a}")


def get_safe_filename(photo) -> str:
    """Generate a date-prefixed unique filename."""
    try:
        date_str = photo.date.strftime("%Y-%m-%d") if photo.date else "unknown"
    except Exception:
        date_str = "unknown"
    stem = Path(photo.original_filename or "photo").stem
    ext = Path(photo.original_filename or "photo.jpg").suffix.lower() or ".jpg"
    return f"{date_str}_{stem}_{photo.uuid[:8]}{ext}"


def collect_photos(db) -> list:
    """Gather unique photos from People + Albums config."""
    seen: set[str] = set()
    photos = []

    for person_name in KIDS_PEOPLE:
        matches = db.photos(persons=[person_name])
        before = len(seen)
        for p in matches:
            if p.uuid not in seen:
                seen.add(p.uuid)
                photos.append(p)
        added = len(seen) - before
        print(f"  People '{person_name}': {len(matches)} photos ({added} new unique)")

    for album_name in KIDS_ALBUMS:
        # Try regular albums first, then shared albums
        matches = db.photos(albums=[album_name])
        if not matches:
            # Shared album (iCloud shared with family/friends)
            matches = db.photos(albums=[album_name], shared=True)
        before = len(seen)
        for p in matches:
            if p.uuid not in seen:
                seen.add(p.uuid)
                photos.append(p)
        added = len(seen) - before
        kind = "shared album" if not db.photos(albums=[album_name]) else "album"
        print(f"  {kind.capitalize()}  '{album_name}': {len(matches)} photos ({added} new unique)")

    return photos


def copy_photos(photos: list, dry_run: bool = False) -> dict:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    existing = {f.name for f in PHOTOS_DIR.iterdir() if f.is_file()}

    copied = skipped = errors = unsupported = 0

    for photo in photos:
        filename = get_safe_filename(photo)
        ext = Path(filename).suffix.lower()

        if ext not in SUPPORTED_EXTS:
            unsupported += 1
            continue

        if filename in existing:
            skipped += 1
            continue

        if dry_run:
            print(f"  [would copy] {filename}")
            copied += 1
            continue

        try:
            src = photo.path
            if not src or not Path(src).exists():
                src = photo.path_edited
            if not src or not Path(src).exists():
                errors += 1
                continue

            shutil.copy2(src, PHOTOS_DIR / filename)
            copied += 1

            if copied % 100 == 0:
                print(f"  Copied {copied} photos...")

        except Exception as e:
            print(f"  ✗ {filename}: {e}")
            errors += 1

    return {"copied": copied, "skipped": skipped, "errors": errors, "unsupported": unsupported}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without copying")
    parser.add_argument("--list-people", action="store_true", help="List all recognized people")
    parser.add_argument("--list-albums", action="store_true", help="List all album names")
    args = parser.parse_args()

    db = open_db()

    if args.list_people:
        list_people(db)
        return

    if args.list_albums:
        list_albums(db)
        return

    if not KIDS_PEOPLE and not KIDS_ALBUMS:
        print("Nothing configured. Set KIDS_PEOPLE and/or KIDS_ALBUMS in .env")
        print("  Example: KIDS_PEOPLE=白小白")
        print("  Example: KIDS_ALBUMS=This is us")
        print("\nTo explore available names:")
        print("  python scripts/sync_photos.py --list-people")
        print("  python scripts/sync_photos.py --list-albums")
        return

    print(f"\nCollecting photos...")
    photos = collect_photos(db)
    print(f"\nTotal unique photos to sync: {len(photos)}")

    if not photos:
        print("No photos found. Run --list-people or --list-albums to check names.")
        return

    action = "[DRY RUN] Would copy" if args.dry_run else "Copying"
    print(f"\n{action} to {PHOTOS_DIR}...")
    stats = copy_photos(photos, dry_run=args.dry_run)

    print(f"\nDone!")
    print(f"  {'Would copy' if args.dry_run else 'Copied'}:  {stats['copied']}")
    print(f"  Skipped (already exist): {stats['skipped']}")
    if stats["errors"]:
        print(f"  Errors: {stats['errors']}")

    if not args.dry_run and stats["copied"] > 0:
        print(f"\nNext steps:")
        print(f"  python scripts/photo_analyzer.py   # analyze up to {os.getenv('DAILY_PHOTO_LIMIT', 50)} photos today")
        print(f"  python scripts/fusion_engine.py    # update memory store")


if __name__ == "__main__":
    main()
