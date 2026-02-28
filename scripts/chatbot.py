"""
chatbot.py
----------
The story-telling chatbot. Kids type questions or topics, and the chatbot
narrates their memories back to them in a warm, personal story format.

Retrieval: semantic embedding search (Zhipu embedding-2, cosine similarity)
Generation: DeepSeek (via OpenAI-compatible API)

Usage:
    python scripts/chatbot.py

Requires in .env:
    OPENAI_API_KEY    — DeepSeek API key
    OPENAI_BASE_URL   — https://api.deepseek.com/v1
    ZHIPU_API_KEY     — for query embedding
    CHILD_NAME        — child's name
"""

import os
import sys
import json
from datetime import date
from pathlib import Path

import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from cost_tracker import record, get_remaining_budget, daily_summary, COST_PER_CHAT_TURN

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
MEMORIES_FILE = BASE_DIR / "data" / "fusion" / "memories.json"
EMBEDDINGS_FILE = BASE_DIR / "data" / "fusion" / "embeddings.npy"

CHILD_NAME = os.getenv("CHILD_NAME", "you")
CHILD_NAME_EN = os.getenv("CHILD_NAME_EN", "")

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    COLOR = True
except ImportError:
    COLOR = False


def c(text: str, color_code: str) -> str:
    if COLOR:
        return f"{color_code}{text}{Style.RESET_ALL}"
    return text


# ---------------------------------------------------------------------------
# Semantic search engine
# ---------------------------------------------------------------------------

class SemanticSearch:
    def __init__(self, embeddings: np.ndarray):
        """L2-normalize embeddings so cosine similarity = dot product."""
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.matrix = (embeddings / norms).astype(np.float32)

    def search(self, query_vec: list[float], top_k: int = 8) -> list[tuple[int, float]]:
        qvec = np.array(query_vec, dtype=np.float32)
        qvec /= max(float(np.linalg.norm(qvec)), 1e-9)
        scores = self.matrix @ qvec
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in top_indices if scores[i] > 0.1]


def embed_query(zhipu: OpenAI, query: str) -> list[float]:
    """Get embedding vector for the user's query."""
    resp = zhipu.embeddings.create(model="embedding-2", input=query[:2000])
    return resp.data[0].embedding


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def load_memories() -> list[dict]:
    if not MEMORIES_FILE.exists():
        print(f"Memory file not found: {MEMORIES_FILE}")
        print("Run the ingestion pipeline first:")
        print("  python scripts/photo_analyzer.py")
        print("  python scripts/fusion_engine.py")
        sys.exit(1)
    with open(MEMORIES_FILE, encoding="utf-8") as f:
        memories = json.load(f)
    if not memories:
        print("Memory file is empty. Run the ingestion pipeline first.")
        sys.exit(1)
    return memories


def load_embeddings() -> np.ndarray:
    if not EMBEDDINGS_FILE.exists():
        print(f"Embeddings not found: {EMBEDDINGS_FILE}")
        print("Run: python scripts/fusion_engine.py")
        sys.exit(1)
    return np.load(EMBEDDINGS_FILE)


def retrieve_memories(zhipu: OpenAI, engine: SemanticSearch,
                      memories: list[dict], query: str, top_k: int = 8) -> list[dict]:
    query_vec = embed_query(zhipu, query)
    results = engine.search(query_vec, top_k=top_k)
    hits = [memories[i] for i, _ in results]
    hits.sort(key=lambda m: m.get("date", "") or "")
    return hits


# ---------------------------------------------------------------------------
# Chatbot
# ---------------------------------------------------------------------------

def build_system_prompt(child_name: str, child_name_en: str) -> str:
    name_note = f"（英文名 {child_name_en}）" if child_name_en else ""
    birth_year = int(os.getenv("CHILD_BIRTH_YEAR", date.today().year - 6))
    current_age = date.today().year - birth_year

    return f"""你是{child_name}{name_note}的专属记忆守护者——一位温暖的家人，珍藏着关于他成长的一切记忆。

{child_name}今年{current_age}岁（{birth_year}年出生）。你现在正在和他说话。

【说话方式】
- 始终用"你"直接和{child_name}说话，让他感到被看见、被珍视
- 根据{child_name}当前年龄（{current_age}岁）调整语言：用生动简洁的词汇、短句、活泼的比喻（比如"你像小兔子一样蹦蹦跳跳"）
- 讲述不同时期的回忆时，自然地体现他当时的年龄感：更小的时候用更柔软稚嫩的语气，近期的用更贴近现在的语气
- 随着{child_name}每年长大，你的语言也自然成熟

【叙事风格】
- 把记忆编织成流动温暖的故事，像家人围炉夜话时娓娓道来，而非列清单
- 当记忆中有具体地点时，一定要说出地名（城市、景点、餐厅名等）——地点是故事的一部分
- 直接描述{child_name}做了什么、感受到了什么——不要提及信息的来源或载体
- 绝对不要说"在一张照片里""照片显示""日记中写道""根据记录"等——就像亲历者在讲述真实的记忆，不是在读档案
- 如果多段记忆相关，把它们串联成一个完整的故事

【语言】
- 始终使用和{child_name}相同的语言回复（他用中文就用中文，用英文就用英文）
- 如果没有某段记忆，温柔地告诉他，并邀请他来分享更多"""


def format_context(memories: list[dict]) -> str:
    if not memories:
        return "No specific memories found for this query."
    lines = ["Here are the relevant memories I found:\n"]
    for m in memories:
        date_label = f"[{m['date']}]" if m.get("date") and m["date"] not in ("unknown", "unknown date") else "[date unknown]"
        mem_type = "Photo" if m.get("type") == "photo" else "Diary"
        lines.append(f"--- {mem_type} {date_label} ---")
        lines.append(m.get("content", ""))
        lines.append("")
    return "\n".join(lines)


def chat(llm: OpenAI, system_prompt: str, context: str, user_message: str) -> str:
    response = llm.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"[Memory context]\n{context}"},
            {"role": "user", "content": user_message},
        ],
        temperature=0.8,
        max_tokens=1200,
    )
    return response.choices[0].message.content.strip()


def print_welcome(child_name: str, memory_count: int):
    width = 55
    print()
    print(c("=" * width, Fore.CYAN if COLOR else ""))
    print(c(f"  ✨  {child_name}'s Memory Book  ✨", Fore.YELLOW if COLOR else ""))
    print(c(f"  {memory_count} memories · semantic search powered by Zhipu", Fore.CYAN if COLOR else ""))
    print(c("=" * width, Fore.CYAN if COLOR else ""))
    print()
    print(c("Ask me anything about your life!", Fore.GREEN if COLOR else ""))
    print(c('Examples: "Tell me about my birthday"', Fore.WHITE if COLOR else ""))
    print(c('          "What was I like when I was little?"', Fore.WHITE if COLOR else ""))
    print(c('          "我小时候最喜欢什么？"', Fore.WHITE if COLOR else ""))
    print(c('Type "exit" to leave.', Fore.WHITE if COLOR else ""))
    print()


def main():
    memories = load_memories()
    embeddings = load_embeddings()

    if len(embeddings) != len(memories):
        print(f"⚠ Embedding count ({len(embeddings)}) doesn't match memories ({len(memories)}).")
        print("Run: python scripts/fusion_engine.py")
        sys.exit(1)

    print("Loading semantic search index...")
    engine = SemanticSearch(embeddings)
    print(f"Ready. {len(memories)} memories indexed.")

    llm = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
    )
    zhipu = OpenAI(
        api_key=os.getenv("ZHIPU_API_KEY"),
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )

    system_prompt = build_system_prompt(CHILD_NAME, CHILD_NAME_EN)
    print_welcome(CHILD_NAME, len(memories))
    print(c(daily_summary(), Fore.CYAN if COLOR else ""))
    print()

    while True:
        try:
            user_input = input(c(f"{CHILD_NAME} > ", Fore.GREEN if COLOR else "")).strip()
        except (EOFError, KeyboardInterrupt):
            print(c("\n\nGoodbye! Come back anytime to explore your memories.", Fore.YELLOW if COLOR else ""))
            break

        if not user_input:
            continue
        if user_input.lower() in ("/budget", "/cost", "花了多少钱"):
            print(c(daily_summary(), Fore.CYAN if COLOR else ""))
            print()
            continue
        if user_input.lower() in ("exit", "quit", "bye", "再见", "退出"):
            print(c("\nGoodbye! Come back anytime to explore your memories.", Fore.YELLOW if COLOR else ""))
            break

        print(c("\n✨ ", Fore.YELLOW if COLOR else ""), end="", flush=True)
        try:
            if get_remaining_budget() < COST_PER_CHAT_TURN:
                print(c("Daily budget reached. Come back tomorrow!", Fore.YELLOW if COLOR else ""))
                break
            hits = retrieve_memories(zhipu, engine, memories, user_input)
            context = format_context(hits)
            response = chat(llm, system_prompt, context, user_input)
            record("chatbot", COST_PER_CHAT_TURN, turns=1)
            print(c(response, Fore.WHITE if COLOR else ""))
        except Exception as e:
            print(c(f"Error: {e}", Fore.RED if COLOR else ""))

        print()


if __name__ == "__main__":
    main()
