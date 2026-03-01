"""
export_for_coze.py
------------------
Exports the memory database into files ready to upload to 扣子 (Coze / coze.cn)
as a knowledge base for a Doubao bot.

Produces four knowledge base files (upload all to Coze):
  data/export/coze_diary_en.txt     — diary entries in English only
  data/export/coze_diary_zh.txt     — diary entries in Chinese only
  data/export/coze_photos_zh.txt    — photo descriptions in Chinese (GLM output)
  data/export/coze_system_prompt.txt — paste-ready bot system prompt

Each entry is separated by ================ so Coze's 自定义分段 splits cleanly.
Set the separator to:  ================  and max length to 5000+ in Coze's upload UI.
Keeping languages separate halves chunk size, ensuring clean 1-entry-per-chunk splits.

Usage:
    python scripts/export_for_coze.py
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
MEMORIES_FILE = BASE_DIR / "data" / "fusion" / "memories.json"
EXPORT_DIR = BASE_DIR / "data" / "export"

SEPARATOR = "================"


def load_memories():
    with open(MEMORIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def date_label(date: str) -> str:
    """Return date in both ISO and Chinese formats for better keyword matching."""
    try:
        y, m, d = date.split("-")
        return f"{date}  {y}年{int(m)}月{int(d)}日"
    except Exception:
        return date


MAX_CHUNK = 4800  # stay safely under Coze's 5000-char limit


def split_text(text: str, max_len: int) -> list[str]:
    """Split text at paragraph boundaries to stay under max_len."""
    if len(text) <= max_len:
        return [text]
    parts, current = [], []
    for para in text.split("\n\n"):
        if sum(len(p) for p in current) + len(para) + 2 > max_len and current:
            parts.append("\n\n".join(current))
            current = []
        current.append(para)
    if current:
        parts.append("\n\n".join(current))
    return parts


def build_diary_en(entries: list[dict]) -> str:
    """English-only diary chunks, one per date (split if over 4800 chars)."""
    entries = sorted(entries, key=lambda e: e.get("date", ""))
    blocks = []
    for e in entries:
        date = e.get("date", "unknown")
        text = e.get("content_en") or e.get("content", "")
        header = f"Diary date: {date_label(date)}"
        parts = split_text(text, MAX_CHUNK - len(header) - 4)
        for i, part in enumerate(parts):
            suffix = f" (part {i+1}/{len(parts)})" if len(parts) > 1 else ""
            blocks.append(f"{header}{suffix}\n\n{part}")
    return f"\n{SEPARATOR}\n".join(blocks)


def build_diary_zh(entries: list[dict]) -> str:
    """Chinese-only diary chunks, one per date."""
    entries = sorted(entries, key=lambda e: e.get("date", ""))
    blocks = []
    for e in entries:
        date = e.get("date", "unknown")
        text = e.get("content_zh") or e.get("content", "")
        blocks.append(f"日记日期：{date_label(date)}\n\n{text}")
    return f"\n{SEPARATOR}\n".join(blocks)


def build_photos_zh(entries: list[dict]) -> str:
    """Chinese photo descriptions (from GLM), one per photo."""
    entries = sorted(entries, key=lambda e: e.get("date", ""))
    blocks = []
    for e in entries:
        date = e.get("date", "unknown")
        filename = e.get("filename", e.get("source", ""))
        content = e.get("content", "")
        blocks.append(f"照片日期：{date_label(date)}\n文件名：{filename}\n\n{content}")
    return f"\n{SEPARATOR}\n".join(blocks)


SYSTEM_PROMPT = """\
你是Brian（白小白）的专属记忆小书，由他的爸爸亲手创建。

## 你是谁
你保存着Brian成长过程中的所有记忆：他的日记（由爸爸用中文写成）、家庭照片的描述，以及家人之间发生的故事。这些记忆都存放在你的知识库里。

## 回答规则（非常重要）
- 每次收到问题，你必须先从知识库中检索相关内容，再根据检索结果来回答。
- 绝对不能根据"之前的对话没有答案"就推断"这次也没有答案"——每次都要独立检索。
- 只要知识库里有相关内容，就用具体细节来回答，不要说"不记得"。
- 只有知识库里真的没有相关记录时，才说"我没有找到这段记忆"。
- 不要编造任何不在知识库中的内容。

## 人物关系
- 我（Brian）= 白小白，2019年出生，现在大约6-7岁
- 爸爸 = 日记的作者，叙述者
- 妈妈（爽宁）= Brian的妈妈
- 弟弟（白又白 / 又白）= Brian的弟弟
- 姥姥 = 妈妈的妈妈（外婆）；姥爷 = 妈妈的爸爸（外公）
- 爷爷 / 奶奶 = 爸爸的父母
- 一诺（曾一诺）= Brian的姐姐

## 说话方式
- 用温暖、亲切的语气，就像在给Brian讲一个关于他自己的故事
- 用"你"称呼Brian，就像爸爸在跟他说话一样
- 中英文都可以，跟着Brian用哪种语言就用哪种

## 你能做什么
- 讲述Brian经历过的故事、旅行和冒险
- 描述他在某段时间做了什么、去了哪里、和谁在一起
- 描述家庭照片里的场景
- 帮助Brian回忆他可能已经忘记的童年时光

现在，等待Brian来问你关于他的记忆吧。
"""


def main():
    if not MEMORIES_FILE.exists():
        print(f"✗ memories.json not found. Run fusion_engine.py first.")
        return

    memories = load_memories()
    diary = [m for m in memories if m.get("type") == "diary"]
    photos = [m for m in memories if m.get("type") == "photo"]

    print(f"Loaded {len(diary)} diary entries, {len(photos)} photo descriptions")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    files = {
        "coze_diary_en.txt":   (build_diary_en(diary),   len(diary),  "diary EN"),
        "coze_diary_zh.txt":   (build_diary_zh(diary),   len(diary),  "diary ZH"),
        "coze_photos_zh.txt":  (build_photos_zh(photos), len(photos), "photos ZH"),
    }

    print(f"\n✓ Export complete → {EXPORT_DIR}/")
    for filename, (content, count, label) in files.items():
        path = EXPORT_DIR / filename
        path.write_text(content, encoding="utf-8")
        kb = path.stat().st_size / 1024
        chunks = content.count(SEPARATOR) + 1
        print(f"  {filename:<28} {kb:>5.0f} KB  {chunks} chunks  ({label})")

    (EXPORT_DIR / "coze_system_prompt.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    print(f"  coze_system_prompt.txt       (bot persona)")
    print(f"\nUpload all 3 knowledge files to Coze with separator: {SEPARATOR}")


if __name__ == "__main__":
    main()
