"""
parse_wechat.py
---------------
Reads data/wechat/all_messages.json (produced by export_wechat_raw.py),
filters to messages relevant to Brian and key family members, groups by date,
summarises each day via DeepSeek, and writes data/fusion/wechat_parsed.json
ready for fusion_engine.py.

To extract memories for a different person in future, update SUBJECT_KEYWORDS
and FAMILY_KEYWORDS below and re-run — no database access needed.

Usage:
    python scripts/parse_wechat.py
    python scripts/parse_wechat.py --days 90     # only last N days
    python scripts/parse_wechat.py --limit 500   # cap messages processed
"""

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_DIR    = Path(__file__).parent.parent
RAW_FILE    = BASE_DIR / "data" / "wechat" / "all_messages.json"
OUT_FILE    = BASE_DIR / "data" / "fusion" / "wechat_parsed.json"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
)

# ---------------------------------------------------------------------------
# Filter configuration — edit here to extract for a different person
# ---------------------------------------------------------------------------

# Primary subject: days must mention at least one of these
SUBJECT_KEYWORDS = ["白小白", "小白", "白宇棠"]   # Brian

# Family context: only messages mentioning these pass the message-level filter
FAMILY_KEYWORDS = SUBJECT_KEYWORDS + [
    "又白", "弟弟",           # younger brother
    "一诺", "曾一诺",         # elder sister
    "爽宁", "妈妈", "好好",   # mom
    "爸爸", "曾哲",           # dad
    "姥姥", "姥爷",           # maternal grandparents
    "爷爷", "奶奶",           # paternal grandparents
    "哥哥",                   # what brother calls Brian
]

MIN_CHARS = 20   # skip days with very little content after filtering

# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def mentions_subject(msgs: list[str]) -> bool:
    return any(kw in msg for msg in msgs for kw in SUBJECT_KEYWORDS)


def filter_family(msgs: list[str]) -> list[str]:
    return [m for m in msgs if any(kw in m for kw in FAMILY_KEYWORDS)]


def make_id(content: str, date: str) -> str:
    return hashlib.md5(f"wechat:{date}{content[:80]}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# DeepSeek summarisation
# ---------------------------------------------------------------------------

SUMMARISE_PROMPT = """\
Below are WeChat family messages from {date}, already filtered to mentions of key family members.

Family:
- Brian = 白小白 / 小白 / 白宇棠, age 5–6 (the main subject)
- Younger brother = 又白 / 弟弟
- Elder sister = 一诺 / 曾一诺
- Mom = 爽宁 / 妈妈 / 好好
- Dad = 爸爸 / 曾哲 (narrator)
- Maternal grandma/grandpa = 姥姥 / 姥爷
- Paternal grandma/grandpa = 奶奶 / 爷爷

Write a single warm English paragraph (3–5 sentences) as a memory entry for Brian.
FOCUS primarily on what Brian did, felt, or experienced that day.
You may briefly include what other family members were doing if it gives useful context for Brian's memory.
Do not mention WeChat or messages. No headers, no bullet points — just the paragraph.

MESSAGES:
{messages}"""


def summarise_day(date: str, msgs: list[str]) -> str:
    batch = "\n".join(f"- {m}" for m in msgs[:80])
    resp = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=512,
        messages=[{"role": "user", "content": SUMMARISE_PROMPT.format(date=date, messages=batch)}],
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",  type=int, default=0,
                        help="Only process messages from last N days (0=all)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max total messages to process (0=all, newest first)")
    args = parser.parse_args()

    if not RAW_FILE.exists():
        print(f"Raw archive not found: {RAW_FILE}")
        print("Run: python scripts/export_wechat_raw.py")
        return

    print(f"Loading {RAW_FILE.name}...")
    raw = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    print(f"  {len(raw):,} total messages in archive")

    # ---- Group by date -----------------------------------------------------
    by_date: defaultdict[str, list[str]] = defaultdict(list)
    for rec in raw:
        by_date[rec["date"]].append(rec["text"])

    # ---- Apply --days filter ------------------------------------------------
    if args.days:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        by_date = defaultdict(list, {d: v for d, v in by_date.items() if d >= cutoff})
        print(f"  --days {args.days}: {len(by_date)} days remaining")

    # ---- Message-level filter: keep only family-relevant messages ----------
    by_date = defaultdict(list, {d: filter_family(v) for d, v in by_date.items()})
    by_date = defaultdict(list, {d: v for d, v in by_date.items() if v})

    # ---- Day-level filter: must mention subject (Brian) --------------------
    by_date = defaultdict(list, {d: v for d, v in by_date.items() if mentions_subject(v)})
    print(f"  Days mentioning Brian: {len(by_date)}")

    dates = sorted(by_date.keys())

    # ---- Apply --limit (newest days first) ---------------------------------
    if args.limit:
        kept: dict[str, list[str]] = {}
        count = 0
        for d in reversed(dates):
            msgs = by_date[d]
            if count + len(msgs) > args.limit:
                msgs = msgs[:args.limit - count]
            kept[d] = msgs
            count += len(msgs)
            if count >= args.limit:
                break
        by_date = defaultdict(list, kept)
        dates = sorted(by_date.keys())
        print(f"  --limit {args.limit}: {len(dates)} days")

    # ---- Skip already-processed dates --------------------------------------
    existing: dict[str, dict] = {}
    if OUT_FILE.exists():
        for entry in json.loads(OUT_FILE.read_text(encoding="utf-8")):
            existing[entry["date"]] = entry
        print(f"  {len(existing)} dates already processed — skipping")

    to_process = [d for d in dates if d not in existing]
    if not to_process:
        print("Nothing new to process.")
        return

    print(f"\nSummarising {len(to_process)} day(s) via DeepSeek...")
    results = list(existing.values())

    for date in tqdm(to_process, desc="Days"):
        msgs = by_date[date]
        raw_zh = "\n".join(msgs)
        if len(raw_zh) < MIN_CHARS:
            continue

        try:
            summary_en = summarise_day(date, msgs)
            bilingual  = f"{summary_en}\n\n[中文原文]\n{raw_zh[:3000]}"
            entry = {
                "id":         make_id(bilingual, date),
                "date":       date,
                "content":    bilingual,
                "content_en": summary_en,
                "content_zh": raw_zh[:3000],
                "source":     "wechat_messages",
                "type":       "wechat",
                "msg_count":  len(msgs),
            }
        except Exception as exc:
            print(f"\n  {date}: {exc} — storing raw Chinese only")
            entry = {
                "id":        make_id(raw_zh, date),
                "date":      date,
                "content":   raw_zh[:3000],
                "content_zh": raw_zh[:3000],
                "source":    "wechat_messages",
                "type":      "wechat",
                "msg_count": len(msgs),
            }

        results.append(entry)
        time.sleep(0.15)

    results.sort(key=lambda e: e.get("date", ""))

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✓ {len(results)} days → {OUT_FILE}")
    if results:
        print(f"  Date range: {results[0]['date']} → {results[-1]['date']}")
    print("\nNext: python scripts/fusion_engine.py")


if __name__ == "__main__":
    main()
