"""
dedup_photos.py
---------------
Detects near-duplicate photos in data/photos/ and moves duplicates to
data/photos/duplicates/ (never deleted — always reversible).

"Near-duplicate" = multiple shots taken within a short time window
(burst mode, or same scene shot several times quickly).

Strategy:
  1. Read EXIF timestamp from each photo
  2. Sort all photos chronologically
  3. Cluster photos taken within --window seconds of each other
  4. Within each cluster, keep the largest file (proxy for best quality)
  5. Move the rest to data/photos/duplicates/

Usage:
    python scripts/dedup_photos.py              # default 30-second window, dry-run
    python scripts/dedup_photos.py --apply      # actually move duplicates
    python scripts/dedup_photos.py --window 60  # use 60-second window
    python scripts/dedup_photos.py --restore    # move everything back from duplicates/
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from PIL import Image
from PIL.ExifTags import TAGS

BASE_DIR = Path(__file__).parent.parent
PHOTOS_DIR = BASE_DIR / "data" / "photos"
DUPES_DIR = PHOTOS_DIR / "duplicates"

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tiff"}


# ---------------------------------------------------------------------------
# EXIF reading
# ---------------------------------------------------------------------------

def get_exif_datetime(path: Path) -> datetime | None:
    """Read DateTimeOriginal from EXIF. Returns None if unavailable."""
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return None
        for tag_id, value in exif.items():
            if TAGS.get(tag_id) == "DateTimeOriginal":
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def get_date_from_filename(path: Path) -> datetime | None:
    """Fall back to date in filename (YYYY-MM-DD prefix, no time info)."""
    import re
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    return None


def get_timestamp(path: Path) -> tuple[datetime | None, bool]:
    """Returns (datetime, has_time). has_time=False means only date known."""
    dt = get_exif_datetime(path)
    if dt:
        return dt, True
    dt = get_date_from_filename(path)
    return dt, False


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_by_time(photos: list[dict], window_seconds: int) -> list[list[dict]]:
    """
    Group photos into clusters where consecutive photos are within
    window_seconds of each other. Photos without time info are kept alone.
    """
    # Separate photos with time vs date-only
    with_time = [p for p in photos if p["has_time"]]
    date_only = [p for p in photos if not p["has_time"]]

    clusters = []

    # Cluster photos that have full timestamps
    with_time.sort(key=lambda p: p["dt"])
    current_cluster = []
    for photo in with_time:
        if not current_cluster:
            current_cluster = [photo]
        else:
            delta = (photo["dt"] - current_cluster[-1]["dt"]).total_seconds()
            if delta <= window_seconds:
                current_cluster.append(photo)
            else:
                clusters.append(current_cluster)
                current_cluster = [photo]
    if current_cluster:
        clusters.append(current_cluster)

    # Photos with date-only: group by date, but treat each as solo
    # (can't tell if they're bursts without time info)
    for photo in date_only:
        clusters.append([photo])

    return clusters


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def load_photos() -> list[dict]:
    """Scan photos dir, read timestamps and file sizes."""
    photos = []
    files = [
        p for p in PHOTOS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]

    print(f"Reading timestamps from {len(files)} photos...")
    for path in files:
        dt, has_time = get_timestamp(path)
        photos.append({
            "path": path,
            "dt": dt,
            "has_time": has_time,
            "size": path.stat().st_size,
        })

    return photos


def find_duplicates(photos: list[dict], window_seconds: int) -> tuple[list[Path], list[list[Path]]]:
    """
    Returns (keepers, duplicate_groups).
    keepers: one photo per cluster (the largest)
    duplicate_groups: list of clusters that had >1 photo
    """
    # Photos without any date at all — keep them all
    no_date = [p for p in photos if p["dt"] is None]
    dateable = [p for p in photos if p["dt"] is not None]

    clusters = cluster_by_time(dateable, window_seconds)

    keepers = []
    duplicate_groups = []
    dupes_to_move = []

    for cluster in clusters:
        if len(cluster) == 1:
            keepers.append(cluster[0]["path"])
        else:
            # Keep largest file, move the rest
            cluster.sort(key=lambda p: p["size"], reverse=True)
            keepers.append(cluster[0]["path"])
            dupes = [p["path"] for p in cluster[1:]]
            dupes_to_move.extend(dupes)
            duplicate_groups.append([p["path"] for p in cluster])

    keepers.extend(p["path"] for p in no_date)

    return dupes_to_move, duplicate_groups


def move_duplicates(dupes: list[Path], dry_run: bool):
    DUPES_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    for src in dupes:
        dst = DUPES_DIR / src.name
        if dry_run:
            moved += 1
        else:
            shutil.move(str(src), dst)
            moved += 1
    return moved


def restore_duplicates():
    if not DUPES_DIR.exists():
        print("No duplicates folder found.")
        return
    files = list(DUPES_DIR.iterdir())
    if not files:
        print("Duplicates folder is empty.")
        return
    for src in files:
        dst = PHOTOS_DIR / src.name
        if not dst.exists():
            shutil.move(str(src), dst)
    print(f"Restored {len(files)} photos back to {PHOTOS_DIR}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=30,
                        help="Time window in seconds to consider shots as the same scene (default: 30)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually move duplicates (default is dry-run/preview)")
    parser.add_argument("--restore", action="store_true",
                        help="Move all files from duplicates/ back to photos/")
    args = parser.parse_args()

    if args.restore:
        restore_duplicates()
        return

    if not PHOTOS_DIR.exists() or not any(PHOTOS_DIR.iterdir()):
        print(f"No photos found in {PHOTOS_DIR}")
        print("Run sync_photos.py first.")
        return

    photos = load_photos()
    total = len(photos)

    print(f"Clustering with {args.window}-second window...")
    dupes, groups = find_duplicates(photos, window_seconds=args.window)

    burst_groups = [g for g in groups if len(g) >= 2]
    kept = total - len(dupes)
    savings_pct = len(dupes) / total * 100 if total else 0
    cost_saved = len(dupes) * 0.003

    print(f"\n{'[DRY RUN] ' if not args.apply else ''}Results:")
    print(f"  Total photos:      {total:,}")
    print(f"  Burst clusters:    {len(burst_groups):,}  (scenes with multiple shots)")
    print(f"  Duplicates found:  {len(dupes):,}  ({savings_pct:.1f}% of total)")
    print(f"  Photos to keep:    {kept:,}")
    print(f"  API cost saved:    ~${cost_saved:.2f}")

    if burst_groups:
        print(f"\nExample burst clusters (showing first 5):")
        for group in burst_groups[:5]:
            sizes = [f"{p.stat().st_size // 1024}KB" for p in group]
            print(f"  {group[0].name[:40]}...")
            print(f"    {len(group)} shots: {', '.join(sizes)}  → keeping largest")

    if not dupes:
        print("\nNo near-duplicates found.")
        return

    if not args.apply:
        print(f"\nRun with --apply to move {len(dupes):,} duplicates to {DUPES_DIR}")
    else:
        moved = move_duplicates(dupes, dry_run=False)
        print(f"\nMoved {moved:,} duplicates to {DUPES_DIR}")
        print(f"Run with --restore to undo this at any time.")
        print(f"\nNext: python scripts/photo_analyzer.py")


if __name__ == "__main__":
    main()
