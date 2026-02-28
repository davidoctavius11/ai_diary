# ai_diary — A Child's Memory Chatbot

Turn a child's photos and handwritten diary into a conversational memory book they can talk to.

> *"What did I do last summer?" — and the bot tells the story back, with real details.*

Built by a father for his son Brian (白小白). The chatbot searches across years of family photos and diary entries to answer questions in the child's own language — Chinese or English.

---

## How it works

```
Mac Photos library          Handwritten diary (scanned)
       │                              │
  sync_photos.py             parse_translate_diary.py
       │                              │
  photo_analyzer.py                   │
  (Zhipu GLM-4V vision)               │  (DeepSeek translation)
       │                              │
       └──────────┬───────────────────┘
                  │
            fusion_engine.py
            (TF-IDF + embeddings)
                  │
            chatbot.py  ──── or ────  web_chatbot.py
            (terminal)               (mobile browser)
```

**AI providers used:**
- [Zhipu GLM-4V-Flash](https://open.bigmodel.cn) — photo scene description (vision)
- [DeepSeek](https://www.deepseek.com) — diary translation CN→EN and chat generation
- Both are called via the **OpenAI Python SDK** (they implement the same API spec)

**No heavy infrastructure needed:**
- Vector search: custom TF-IDF + numpy (no ChromaDB, works on Python 3.14+)
- Storage: plain JSON files
- Runs entirely on a Mac laptop

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/ai_diary.git
cd ai_diary
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys and family details
```

Key settings in `.env`:

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | DeepSeek API key (for translation + chat) |
| `OPENAI_BASE_URL` | `https://api.deepseek.com/v1` |
| `ZHIPU_API_KEY` | Zhipu AI key (for photo analysis) |
| `CHILD_NAME` | Child's Chinese name |
| `CHILD_NAME_EN` | Child's English name |
| `KIDS_PEOPLE` | Face album name(s) in Mac Photos |
| `KIDS_ALBUMS` | Shared album name(s) in Mac Photos |
| `DAILY_PHOTO_LIMIT` | Max photos to analyze per day (cost control) |
| `FAMILY_MEMBERS` | `iPhotoName:称谓` pairs, semicolon-separated |

### 3. Add your data

**Photos** — sync from Mac Photos:
```bash
python scripts/sync_photos.py
python scripts/dedup_photos.py --apply   # remove burst duplicates (reversible)
python scripts/extract_photo_metadata.py
```

**Diary** — save your diary text to:
```
data/diary/brian_diary_2025.txt
```
The parser handles messy OCR, mixed date formats, and bilingual content.

### 4. Run the pipeline

```bash
python scripts/photo_analyzer.py          # analyze photos (respects daily limit)
python scripts/parse_translate_diary.py   # translate diary CN→EN
python scripts/fusion_engine.py           # build memory index
```

### 5. Start chatting

```bash
python scripts/chatbot.py
```

---

## Weekly automation (macOS)

Run the full photo pipeline automatically every Sunday at 3 AM:

```bash
# One-time setup
launchctl load ~/Library/LaunchAgents/com.brian.diary.weekly.plist
```

The LaunchAgent runs `scripts/weekly_photo_sync.sh` which handles:
sync → dedup → metadata → analyze → rebuild index

Logs saved to `logs/weekly_sync_YYYYMMDD.log`.

---

## Deploy to Doubao (optional)

Export knowledge base files for [扣子 Coze](https://www.coze.cn):

```bash
python scripts/export_for_coze.py
```

Upload the 3 files from `data/export/` to Coze with:
- Segmentation: **自定义分段**
- Separator: `================`
- Max length: 5000

Then publish the bot to Doubao for mobile access.

---

## Project structure

```
ai_diary/
├── scripts/
│   ├── sync_photos.py              # pull from Mac Photos by face/album
│   ├── dedup_photos.py             # remove burst duplicates
│   ├── extract_photo_metadata.py   # GPS + face names from Photos library
│   ├── photo_analyzer.py           # GLM vision descriptions
│   ├── parse_translate_diary.py    # parse + translate handwritten diary
│   ├── diary_parser.py             # parse Flomo/Notion/plain text exports
│   ├── fusion_engine.py            # merge all data, build TF-IDF index
│   ├── chatbot.py                  # terminal chatbot
│   ├── export_for_coze.py          # export to Coze knowledge base format
│   ├── cost_tracker.py             # daily API spend tracking
│   ├── build_gallery.py            # HTML photo gallery
│   └── weekly_photo_sync.sh        # cron-ready automation script
├── data/                           # gitignored — your personal data lives here
│   ├── diary/                      # raw diary text files
│   ├── photos/                     # synced photos
│   └── fusion/                     # memories.json, embeddings.npy, gallery.html
├── .env.example                    # config template
├── CLAUDE.md                       # project spec (for Claude Code)
└── requirements.txt
```

---

## Cost

Running this for a year of photos + diary costs roughly:

| Task | Provider | Cost |
|------|----------|------|
| Photo analysis | Zhipu GLM-4V-Flash | ~$0.003/photo |
| Diary translation | DeepSeek | ~$0.01/entry |
| Daily chat | DeepSeek | ~$0.001/message |

A full year of 8,000 photos at 50/day ≈ **$24 total** over 160 days.

---

## Privacy note

This repo contains **no personal data**. The `data/` directory is gitignored.
Your diary, photos, and memories stay on your own machine.
