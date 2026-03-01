"""
export_wechat_raw.py
--------------------
Exports ALL text messages from decrypted WeChat databases into a single
flat JSON file: data/wechat/all_messages.json

This is a one-time archive step. Run it once after decrypting the databases.
Future re-parses (for different people, date ranges, etc.) read from this
JSON — no need to touch the decrypted .db files again.

Each record:
  {
    "date":    "YYYY-MM-DD",
    "ts":      1234567890,       # Unix timestamp (seconds)
    "chat_id": "Msg_abc123",     # WeChat chat identifier (one per contact/group)
    "db":      "message_0",      # source database file
    "type":    1,                # WeChat message type (1=text)
    "text":    "...",            # message content
  }

Usage:
    python scripts/export_wechat_raw.py
    python scripts/export_wechat_raw.py --force   # re-export even if file exists
"""

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import tqdm

BASE_DIR   = Path(__file__).parent.parent
WECHAT_DIR = BASE_DIR / "data" / "wechat" / "decrypted"
OUT_FILE   = BASE_DIR / "data" / "wechat" / "all_messages.json"

TEXT_TYPES = {1}


def get_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur]
    result = [t for t in tables if t.startswith("Msg_")]
    if not result:
        result = [t for t in tables if t.startswith("Chat_")]
    return result


def read_table(conn: sqlite3.Connection, table: str, db_name: str) -> list[dict]:
    try:
        info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        cols = {r[1].lower(): r[1] for r in info}
    except Exception:
        return []

    time_col    = cols.get("create_time") or cols.get("createtime")
    content_col = cols.get("message_content") or cols.get("message") or cols.get("content")
    type_col    = cols.get("local_type") or cols.get("type")

    if not time_col or not content_col:
        return []

    select_cols = [time_col, content_col]
    if type_col:
        select_cols.append(type_col)

    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM \"{table}\" ORDER BY {time_col}"
        ).fetchall()
    except Exception:
        return []

    records = []
    for row in rows:
        ts      = row[0]
        text    = row[1] or ""
        mtype   = row[2] if type_col else 1

        if mtype not in TEXT_TYPES:
            continue

        if isinstance(text, bytes):
            try:
                text = text.decode("utf-8")
            except Exception:
                continue

        # Strip XML metadata from type-49 app messages
        if mtype == 49:
            m = re.search(r"<title>(.*?)</title>", text, re.DOTALL)
            text = m.group(1).strip() if m else ""

        text = text.strip()
        if not text or len(text) < 2:
            continue

        if ts and ts > 1_000_000_000_000:
            ts //= 1000
        try:
            dt   = datetime.fromtimestamp(ts, tz=timezone.utc)
            date = dt.strftime("%Y-%m-%d")
        except Exception:
            continue

        records.append({
            "date":    date,
            "ts":      ts,
            "chat_id": table,
            "db":      db_name,
            "type":    mtype,
            "text":    text,
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Re-export even if all_messages.json already exists")
    args = parser.parse_args()

    if OUT_FILE.exists() and not args.force:
        existing = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        print(f"all_messages.json already exists ({len(existing):,} messages).")
        print("Use --force to re-export.")
        return

    dbs = sorted(WECHAT_DIR.glob("*_plain.db"))
    if not dbs:
        print(f"No decrypted databases in {WECHAT_DIR}")
        print("Run: python scripts/decrypt_wechat_db.py")
        return

    all_records = []

    for db_path in dbs:
        db_name = db_path.stem.replace("_plain", "")
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception as e:
            print(f"  Cannot open {db_path.name}: {e}")
            continue

        tables = get_tables(conn)
        print(f"{db_path.name}: {len(tables)} chat tables", end="", flush=True)

        count = 0
        for table in tqdm.tqdm(tables, desc=f"  {db_name}", leave=False):
            records = read_table(conn, table, db_name)
            all_records.extend(records)
            count += len(records)

        conn.close()
        print(f" → {count:,} messages")

    all_records.sort(key=lambda r: r["ts"])

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    dates = [r["date"] for r in all_records]
    print(f"\n✓ {len(all_records):,} messages exported → {OUT_FILE}")
    if dates:
        print(f"  Date range: {min(dates)} → {max(dates)}")
    print("\nNext: python scripts/parse_wechat.py")


if __name__ == "__main__":
    main()
