"""
photo_analyzer.py
-----------------
Analyzes photos in data/photos/ using Zhipu GLM-4V-Flash (vision API).
Generates rich Chinese descriptions for each photo, enriched with:
  - Person names + family relationships (from iPhoto face recognition)
  - GPS location (from photo metadata)

Respects DAILY_PHOTO_LIMIT from .env to control API costs.

Usage:
    python scripts/photo_analyzer.py              # analyze up to daily limit
    python scripts/photo_analyzer.py --limit 100  # override limit for this run
    python scripts/photo_analyzer.py --limit 0    # no limit (process all)
    python scripts/photo_analyzer.py --reanalyze  # redo already-analyzed photos

Requires:
    ZHIPU_API_KEY in your .env file
    Run extract_photo_metadata.py first for enriched descriptions
"""

import io
import os
import json
import base64
import hashlib
import re
from pathlib import Path
from datetime import datetime

import argparse
import sys

from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
from PIL import Image
from PIL.ExifTags import TAGS
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from cost_tracker import (
    check_budget, record, get_remaining_budget, max_photos_remaining,
    daily_summary, COST_PER_PHOTO, BudgetExceededError
)

load_dotenv()

DEFAULT_DAILY_LIMIT = int(os.getenv("DAILY_PHOTO_LIMIT", "50"))

BASE_DIR = Path(__file__).parent.parent
PHOTOS_DIR = BASE_DIR / "data" / "photos"
OUTPUT_FILE = BASE_DIR / "data" / "fusion" / "photos_analyzed.json"
METADATA_FILE = PHOTOS_DIR / "photo_metadata.json"

client = OpenAI(
    api_key=os.getenv("ZHIPU_API_KEY"),
    base_url="https://open.bigmodel.cn/api/paas/v4/",
)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}

ANALYSIS_PROMPT_TEMPLATE = """请用中文描述这张照片，目标是帮助照片中的孩子日后看到文字时，能够清晰地回忆起当时的具体场景。
{context_block}
请重点描述以下内容：
- **时间与地点**：这是在哪里？什么季节或时间段？（若已知地点请直接写出地名）
- **在场的人**：有谁？他们各自在做什么动作？位置关系如何？
- **活动与事件**：正在发生什么具体的事情？是在吃饭、玩耍、旅行、运动还是其他？
- **环境细节**：周围有什么具体的物品、建筑、自然景物、食物、装饰等？
- **人物状态**：简要描述外貌、穿着、动作姿态即可，不要过度解读表情或内心感受

最后用2-3句话做整体描述，语言要具体客观：说清楚这是什么地方、有什么人、在做什么事。不要出现任何关于心情、感受、氛围的词语（如"温馨""开心""充满爱"等）。请全部用中文回答。"""


def load_family_map() -> dict[str, str]:
    """Parse FAMILY_MEMBERS env var into {iPhoto_name: role} dict."""
    raw = os.getenv("FAMILY_MEMBERS", "")
    family = {}
    for item in raw.split(";"):
        if ":" in item:
            name, role = item.split(":", 1)
            family[name.strip()] = role.strip()
    return family


def load_photo_metadata() -> dict:
    """Load person + location metadata extracted from iPhoto."""
    if METADATA_FILE.exists():
        with open(METADATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_context_block(filename: str, photo_metadata: dict, family_map: dict) -> str:
    """Build the enriched context block to inject into the prompt."""
    meta = photo_metadata.get(filename, {})
    lines = []

    # Rich location: POI + full hierarchy + season
    loc_detail = meta.get("location_detail") or {}
    location   = meta.get("location")
    season     = meta.get("season")

    if loc_detail.get("poi"):
        lines.append(f"拍摄地点：{loc_detail['poi']}（{location}）")
    elif location:
        lines.append(f"拍摄地点：{location}")

    if season and location:
        lines.append(f"拍摄季节：{season}")

    persons = meta.get("persons", [])
    if persons:
        labeled = []
        for name in persons:
            role = family_map.get(name)
            labeled.append(f"{name}（{role}）" if role else name)
        lines.append(f"照片中识别的人物：{'、'.join(labeled)}")
        lines.append("请在描述中使用以上人物的身份称谓（如妈妈、爸爸、大儿子Brian等），而非泛指'小孩''女性'等。")

    if not lines:
        return ""

    block = "\n".join(lines)
    return f"\n【已知信息，请一定融入描述】\n{block}\n"


def get_exif_date(image_path: Path) -> str | None:
    """Extract date from image EXIF metadata."""
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if not exif_data:
            return None
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "DateTimeOriginal":
                dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def guess_date_from_filename(filename: str) -> str | None:
    """Try to extract a date from the filename (e.g. 2023-08-15_beach.jpg)."""
    for pattern in [r"(\d{4}[-_]\d{2}[-_]\d{2})", r"(\d{8})"]:
        match = re.search(pattern, filename)
        if match:
            raw = match.group(1).replace("_", "-")
            if len(raw) == 8:
                raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
            try:
                datetime.strptime(raw, "%Y-%m-%d")
                return raw
            except ValueError:
                continue
    return None


MAX_IMAGE_PX = 1120  # Zhipu GLM-4V max dimension


def encode_image(image_path: Path) -> tuple[str, str]:
    """Resize + compress image and return (base64_data, media_type)."""
    img = Image.open(image_path).convert("RGB")
    img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return data, "image/jpeg"


def analyze_photo(image_path: Path, context_block: str = "") -> dict:
    """Send photo to Zhipu GLM-4V-Flash and return structured description."""
    date = get_exif_date(image_path) or guess_date_from_filename(image_path.name) or "unknown date"
    image_data, media_type = encode_image(image_path)
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(context_block=context_block)

    message = client.chat.completions.create(
        model="glm-4v-flash",
        max_tokens=600,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    description = message.choices[0].message.content.strip()
    content_id = hashlib.md5(f"{image_path.name}{date}".encode()).hexdigest()[:12]

    return {
        "id": content_id,
        "filename": image_path.name,
        "date": date,
        "type": "photo",
        "source": str(image_path),
        "content": description,
    }


def load_existing(output_file: Path) -> dict:
    """Load already-analyzed photos to avoid re-processing."""
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            items = json.load(f)
        return {item["filename"]: item for item in items}
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_DAILY_LIMIT,
                        help=f"Max photos to analyze this run (0=no limit, default={DEFAULT_DAILY_LIMIT})")
    parser.add_argument("--reanalyze", action="store_true",
                        help="Re-analyze already-processed photos (replaces old descriptions)")
    args = parser.parse_args()
    limit = args.limit

    if not os.getenv("ZHIPU_API_KEY"):
        print("Error: ZHIPU_API_KEY not set in .env")
        print("Get a free key at: https://open.bigmodel.cn")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    photo_files = [
        p for p in PHOTOS_DIR.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not photo_files:
        print(f"No photos found in {PHOTOS_DIR}")
        print("Run sync_photos.py first, or add photos manually to data/photos/")
        return

    # Load enrichment data
    photo_metadata = load_photo_metadata()
    family_map = load_family_map()

    if photo_metadata:
        print(f"Loaded metadata for {len(photo_metadata)} photos "
              f"({sum(1 for m in photo_metadata.values() if m.get('persons'))} with people, "
              f"{sum(1 for m in photo_metadata.values() if m.get('location'))} with location)")
    else:
        print("No photo metadata found. Run extract_photo_metadata.py for enriched descriptions.")

    existing = load_existing(OUTPUT_FILE)
    if args.reanalyze:
        to_process = photo_files
        print(f"\nReanalyze mode: will re-process all {len(to_process)} photos.")
    else:
        to_process = [p for p in photo_files if p.name not in existing]

    to_process.sort(key=lambda p: p.name, reverse=True)

    budget_cap = max_photos_remaining()
    effective_limit = min(limit, budget_cap) if limit > 0 else budget_cap

    print(f"\nFound {len(photo_files)} photos total. {len(existing)} already analyzed, {len(to_process)} pending.")
    print(daily_summary())

    if budget_cap == 0:
        print(f"\nDaily budget ${float(os.getenv('DAILY_BUDGET_USD', 10)):.2f} already reached. Run again tomorrow.")
        return

    if len(to_process) > effective_limit:
        print(f"\nWill analyze {effective_limit} photos today "
              f"(limit: {limit}/day, budget cap: {budget_cap} photos, ~${effective_limit * COST_PER_PHOTO:.2f})")
        to_process = to_process[:effective_limit]
    else:
        print(f"\nWill analyze {len(to_process)} photos (~${len(to_process) * COST_PER_PHOTO:.2f})")

    if not to_process:
        print("All photos already analyzed!")
        return

    # Start with existing results (reanalyze replaces entries)
    results_dict = {} if args.reanalyze else dict(existing)
    analyzed_this_run = 0

    for photo_path in tqdm(to_process, desc="Analyzing photos"):
        try:
            check_budget(COST_PER_PHOTO)
            context_block = build_context_block(photo_path.name, photo_metadata, family_map)
            result = analyze_photo(photo_path, context_block)
            results_dict[photo_path.name] = result
            record("photo_analysis", COST_PER_PHOTO, photos=1)
            analyzed_this_run += 1
            print(f"  ✓ {photo_path.name} ({result['date']})")
        except BudgetExceededError as e:
            print(f"\n  Budget cap hit: {e}")
            break
        except Exception as e:
            print(f"  ✗ {photo_path.name}: {e}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(list(results_dict.values()), f, ensure_ascii=False, indent=2)

    remaining_photos = len([p for p in photo_files if p.name not in {r["filename"] for r in results_dict.values()}])

    print(f"\nAnalyzed {analyzed_this_run} photos this run")
    print(daily_summary())
    if remaining_photos > 0:
        print(f"\nRemaining: {remaining_photos} photos — run again tomorrow")


if __name__ == "__main__":
    main()
