"""
fusion_engine.py
----------------
Merges photo descriptions and diary entries into memories.json,
then computes semantic embeddings for every memory using Zhipu embedding-2.

Embeddings are cached in data/fusion/embeddings.npy (numpy array, shape [n, 1024]).
Only new/changed memories are re-embedded — existing ones are reused from cache.

Run this after photo_analyzer.py and diary_parser.py.

Usage:
    python scripts/fusion_engine.py
"""

import json
import os
import time
from pathlib import Path

import numpy as np
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
FUSION_DIR = BASE_DIR / "data" / "fusion"
PHOTOS_FILE  = FUSION_DIR / "photos_analyzed.json"
DIARY_FILE   = FUSION_DIR / "diary_parsed.json"
FUSED_FILE   = FUSION_DIR / "fused_memories.json"
MEMORIES_FILE = FUSION_DIR / "memories.json"
EMBEDDINGS_FILE = FUSION_DIR / "embeddings.npy"
EMBEDDINGS_INDEX = FUSION_DIR / "embeddings_index.json"  # {memory_id: row_in_npy}


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  ⚠ Not found: {path.name} — run the corresponding script first.")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_embedding_cache() -> dict[str, list[float]]:
    """Load cached embeddings keyed by memory ID."""
    if not EMBEDDINGS_FILE.exists() or not EMBEDDINGS_INDEX.exists():
        return {}
    matrix = np.load(EMBEDDINGS_FILE)
    with open(EMBEDDINGS_INDEX, encoding="utf-8") as f:
        index = json.load(f)  # {memory_id: row_idx}
    return {mem_id: matrix[row].tolist() for mem_id, row in index.items()}


def compute_embeddings(memories: list[dict], cache: dict[str, list[float]]) -> np.ndarray:
    """Return embedding matrix [n, 1024] for all memories, using cache where possible."""
    client = OpenAI(
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )

    to_embed = [(i, m) for i, m in enumerate(memories) if m["id"] not in cache]
    embeddings = [cache.get(m["id"]) for m in memories]  # None for new ones

    if not to_embed:
        print("  All embeddings already cached — skipping API calls.")
        return np.array(embeddings, dtype=np.float32)

    print(f"  Computing embeddings for {len(to_embed)} new memories...")
    for batch_start in tqdm(range(0, len(to_embed), 10), desc="  Embedding"):
        batch = to_embed[batch_start:batch_start + 10]
        for idx, m in batch:
            text = m["content"][:2000]  # API limit
            resp = client.embeddings.create(model="embedding-2", input=text)
            embeddings[idx] = resp.data[0].embedding
        if batch_start + 10 < len(to_embed):
            time.sleep(0.5)  # gentle rate-limit buffer

    return np.array(embeddings, dtype=np.float32)


def save_embeddings(memories: list[dict], matrix: np.ndarray):
    np.save(EMBEDDINGS_FILE, matrix)
    index = {m["id"]: i for i, m in enumerate(memories)}
    with open(EMBEDDINGS_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f)


def main():
    print("Loading source data...")
    photos = load_json(PHOTOS_FILE)
    diary  = load_json(DIARY_FILE)
    fused  = load_json(FUSED_FILE) if FUSED_FILE.exists() else []

    all_entries = photos + diary + fused

    if not all_entries:
        print("\nNo data to index. Run photo_analyzer.py and/or diary_parser.py first.")
        return

    print(f"  {len(photos)} photo descriptions")
    print(f"  {len(diary)} diary entries")
    if fused:
        print(f"  {len(fused)} fused memories (diary+photo)")

    all_entries.sort(key=lambda e: e.get("date", "") or "")

    FUSION_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEMORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    dates = [e["date"] for e in all_entries if e.get("date") and e["date"] not in ("unknown", "unknown date")]
    date_range = f"{min(dates)} → {max(dates)}" if dates else "unknown date range"

    fused_note = f" + {len(fused)} fused" if fused else ""
    print(f"\nMemory store: {len(all_entries)} memories ({len(photos)} photos + {len(diary)} diary{fused_note})")
    print(f"Date range: {date_range}")

    # Semantic embeddings
    print("\nBuilding semantic embeddings...")
    cache = load_embedding_cache()
    print(f"  Cache hit: {sum(1 for m in all_entries if m['id'] in cache)}/{len(all_entries)}")
    matrix = compute_embeddings(all_entries, cache)
    save_embeddings(all_entries, matrix)
    print(f"  Embeddings saved: {matrix.shape} → {EMBEDDINGS_FILE.name}")
    print(f"\nReady. Run chatbot.py to start exploring memories.")


if __name__ == "__main__":
    main()
