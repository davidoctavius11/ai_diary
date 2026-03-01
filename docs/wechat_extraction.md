# WeChat Message Extraction — Full Process Guide

## Overview

This document captures the complete process of extracting WeChat Mac message
history into the children's memory chatbot pipeline. Follow this guide if you
need to repeat any step (e.g. after a WeChat update, or to extract memories
for a different family member).

---

## Architecture

```
WeChat Mac (encrypted WCDB databases)
    │
    ▼  [Step 1 — one-time per WeChat version]
Frida key capture (CCKeyDerivationPBKDF hook)
    │  produces: one 64-char hex key per database
    │
    ▼  [Step 2 — one-time per WeChat version]
scripts/wechat/decrypt_wechat_db.py
    │  produces: data/wechat/decrypted/message_N_plain.db (plain SQLite)
    │
    ▼  [Step 3 — run once, re-run after syncing new messages]
scripts/wechat/export_wechat_raw.py
    │  produces: data/wechat/all_messages.json  ← PERMANENT ARCHIVE
    │            (all text messages, no filtering)
    │
    ▼  [Step 4 — run any time, cheap, no DB access]
scripts/wechat/parse_wechat.py
    │  reads:    data/wechat/all_messages.json
    │  produces: data/fusion/wechat_parsed.json
    │            (filtered + summarised via DeepSeek)
    │
    ▼  [Step 5]
scripts/fusion_engine.py
       produces: data/fusion/memories.json + embeddings.npy
```

The key insight: **`all_messages.json` is the permanent raw archive**. Steps 1–3
are painful and need repeating only when WeChat updates. Step 4 is fast and
can be re-run freely to adjust filters, subjects, or date ranges.

---

## Prerequisites

Install once:
```bash
pip install frida-tools
brew install sqlcipher
```

---

## Step 1 — Capture Encryption Keys (Frida)

WeChat uses WCDB (their SQLite fork) with per-database encryption keys.
Each database file has its own 32-byte key. Keys are derived via PBKDF2,
which calls the system `CCKeyDerivationPBKDF` function — that's what we hook.

### 1a. Re-sign WeChat with debugger entitlement (one-time)

Required so macOS allows Frida to attach. Only needs repeating after a
WeChat auto-update replaces the binary.

```bash
# Check if already signed with get-task-allow:
codesign -d --entitlements - /Applications/WeChat.app

# If not (or after an update), re-sign:
cat > /tmp/wechat_debug.entitlements << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.get-task-allow</key><true/>
</dict></plist>
EOF

sudo codesign --remove-signature /Applications/WeChat.app
sudo codesign -s - --entitlements /tmp/wechat_debug.entitlements \
  --deep --force /Applications/WeChat.app
```

If WeChat shows a "damaged" warning after re-signing:
```bash
sudo xattr -rd com.apple.quarantine /Applications/WeChat.app
```

### 1b. Capture keys

**Terminal 1** — start the attach script (leave it waiting):
```bash
bash scripts/wechat/attach_wechat.sh
```

**Then** open WeChat from the Dock.
The script auto-attaches as WeChat starts.

**In WeChat** — log out, then log back in. This forces WeChat to close
and re-open all database files, triggering the PBKDF2 key derivation.

Alternatively:
```bash
bash scripts/wechat/run_frida.sh
```
(runs `frida_wechat_key.js` against the running WeChat process)

**Terminal output** — for each database opened you will see:
```
================================================================
WECHAT KEY (password fed to PBKDF2):
46cd25e87089f5a387ceef5448ab52cec2d165d935c59ab2f6605452a2034d05
================================================================
```

Many keys appear (one per database file plus some system crypto).
Record all unique 64-char hex keys — you need one per message DB.

### Key → database mapping (captured 2026-03-01)

| Database       | Key (first 16 chars…) |
|----------------|----------------------|
| message_0.db   | 46cd25e87089f5a3…   |
| message_1.db   | 71b3cdab57ed8bec…   |
| message_2.db   | ea25ab697b9a6517…   |
| message_3.db   | 1ba6a05dcb11a347…   |

> **Note:** Keys change if you log out completely or reinstall WeChat.
> After a WeChat auto-update the binary changes but keys usually persist.

---

## Step 2 — Decrypt Databases

```bash
source venv/bin/activate
python scripts/wechat/decrypt_wechat_db.py
```

This tries the key from `/tmp/wechat_key.txt` against all
`message_*.db` files. If using a different key per DB, pass `--key`:

```bash
python scripts/wechat/decrypt_wechat_db.py --key <64-char-hex>
```

Or use the bulk try-all-keys approach (more robust):
```bash
bash /tmp/try_keys.sh   # see script for key list
```

Output: `data/wechat/decrypted/message_N_plain.db` (plain SQLite, readable).

### Database schema

Tables: `Msg_<md5hash>` — one table per WeChat contact or group chat.

Key columns:
| Column           | Type    | Description                     |
|------------------|---------|---------------------------------|
| `create_time`    | INTEGER | Unix timestamp (seconds)        |
| `local_type`     | INTEGER | 1=text, 3=image, 34=voice, 43=video |
| `message_content`| TEXT    | Message text                    |
| `real_sender_id` | INTEGER | Internal sender ID              |

---

## Step 3 — Export Raw Archive

Run once after decryption. Exports **all text messages** to a flat JSON
file with no filtering.

```bash
python scripts/wechat/export_wechat_raw.py
```

Output: `data/wechat/all_messages.json`

Each record:
```json
{
  "date":    "2025-12-01",
  "ts":      1748736000,
  "chat_id": "Msg_abc123def456",
  "db":      "message_0",
  "type":    1,
  "text":    "白小白今天..."
}
```

To refresh after syncing new messages from phone (repeat Steps 1–2 for
new data, then):
```bash
python scripts/wechat/export_wechat_raw.py --force
```

---

## Step 4 — Parse & Filter for a Person

```bash
python scripts/wechat/parse_wechat.py              # all history
python scripts/wechat/parse_wechat.py --days 90   # last 90 days only
```

**To extract memories for a different family member**, edit the top of
`scripts/wechat/parse_wechat.py`:

```python
# Primary subject: days must mention at least one of these
SUBJECT_KEYWORDS = ["又白", "弟弟"]   # ← change to younger brother

# Family context filter (keep broad for context)
FAMILY_KEYWORDS = SUBJECT_KEYWORDS + [...]
```

Also update `SUMMARISE_PROMPT` to name the new subject.
Then delete the old output and re-run:
```bash
rm data/fusion/wechat_parsed.json
python scripts/wechat/parse_wechat.py
```

**No database access needed** — reads only from `all_messages.json`.

### Filtering logic

1. **Message filter**: keep only messages that mention any family member
   by name (drops neighborhood/community group spam automatically)
2. **Day filter**: keep only days where the primary subject is mentioned
3. **Summarisation**: DeepSeek writes a warm English paragraph per day,
   focused on the subject with family context

Output: `data/fusion/wechat_parsed.json` (same schema as diary entries)

---

## Step 5 — Fuse into Memory Store

```bash
python scripts/fusion_engine.py
```

This merges photos + diary + WeChat into `data/fusion/memories.json`
and rebuilds the TF-IDF embeddings.

---

## When to Repeat Each Step

| Event                          | Steps to repeat |
|--------------------------------|-----------------|
| WeChat auto-updated            | 1a (re-sign), 1b (capture keys), 2, 3 |
| New messages synced from phone | 2, 3 (--force), 4, 5 |
| Want different person's memories | 4 only (edit keywords) |
| Want different date range      | 4 only (--days flag) |
| Chatbot feels outdated         | 4, 5 |

---

## Files Reference

| File | Description |
|------|-------------|
| `scripts/wechat/attach_wechat.sh`    | Waits for WeChat to launch, auto-attaches Frida |
| `scripts/wechat/run_frida.sh`        | Attaches Frida to running WeChat |
| `scripts/wechat/frida_wechat_key.js` | Frida script: hooks CCKeyDerivationPBKDF, prints keys |
| `scripts/wechat/wechat_grab_key.lldb`| LLDB alternative (kept for reference; Frida approach preferred) |
| `scripts/wechat/decrypt_wechat_db.py`| Decrypts WCDB databases using captured keys |
| `scripts/wechat/export_wechat_raw.py`| Exports all messages to all_messages.json |
| `scripts/wechat/parse_wechat.py`     | Filters + summarises for a specific person |
| `data/wechat/decrypted/`      | Plain SQLite databases (keep these) |
| `data/wechat/all_messages.json` | Full raw message archive (keep this) |
| `data/fusion/wechat_parsed.json` | Filtered summaries for chatbot |
