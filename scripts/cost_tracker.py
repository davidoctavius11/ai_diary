"""
cost_tracker.py
---------------
Tracks daily API spending across all scripts and enforces a hard daily cap.

Cost log stored at: data/fusion/cost_log.json
Daily budget set via DAILY_BUDGET_USD in .env (default: $10.00)

Services tracked:
  - photo_analysis  (Claude Haiku vision, ~$0.003/photo)
  - chatbot         (DeepSeek chat, ~$0.001/turn)
"""

import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
COST_LOG = BASE_DIR / "data" / "fusion" / "cost_log.json"

DAILY_BUDGET = float(os.getenv("DAILY_BUDGET_USD", "10.00"))

# Cost estimates per unit
COST_PER_PHOTO = 0.003       # Claude Haiku vision
COST_PER_CHAT_TURN = 0.001   # DeepSeek (rough estimate)


class BudgetExceededError(Exception):
    pass


def _today() -> str:
    return date.today().isoformat()


def _load() -> dict:
    if COST_LOG.exists():
        with open(COST_LOG, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(log: dict):
    COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(COST_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def get_today_spend() -> float:
    """Total USD spent today across all services."""
    log = _load()
    today = log.get(_today(), {})
    return sum(svc.get("cost", 0.0) for svc in today.values())


def get_remaining_budget() -> float:
    return max(0.0, DAILY_BUDGET - get_today_spend())


def max_photos_remaining() -> int:
    """How many more photos can we analyze today within budget."""
    remaining = get_remaining_budget()
    return int(remaining / COST_PER_PHOTO)


def record(service: str, cost: float, **extra):
    """Record a spend event for a service."""
    log = _load()
    today_str = _today()
    if today_str not in log:
        log[today_str] = {}
    if service not in log[today_str]:
        log[today_str][service] = {"cost": 0.0}

    entry = log[today_str][service]
    entry["cost"] = round(entry["cost"] + cost, 6)
    for k, v in extra.items():
        entry[k] = entry.get(k, 0) + v

    _save(log)


def check_budget(planned_cost: float):
    """Raise BudgetExceededError if adding planned_cost would exceed today's cap."""
    spent = get_today_spend()
    if spent + planned_cost > DAILY_BUDGET:
        raise BudgetExceededError(
            f"Daily budget ${DAILY_BUDGET:.2f} would be exceeded "
            f"(spent ${spent:.4f} + planned ${planned_cost:.4f}). "
            f"Remaining: ${DAILY_BUDGET - spent:.4f}"
        )


def daily_summary() -> str:
    """Human-readable summary of today's spending."""
    log = _load()
    today_data = log.get(_today(), {})
    total = sum(s.get("cost", 0) for s in today_data.values())
    remaining = DAILY_BUDGET - total

    lines = [f"Daily budget: ${DAILY_BUDGET:.2f}"]
    if not today_data:
        lines.append("  No spending today yet.")
    for service, data in today_data.items():
        cost = data.get("cost", 0)
        details = []
        if "photos" in data:
            details.append(f"{data['photos']} photos")
        if "turns" in data:
            details.append(f"{data['turns']} chat turns")
        detail_str = f"  ({', '.join(details)})" if details else ""
        lines.append(f"  {service}: ${cost:.4f}{detail_str}")
    lines.append(f"  ─────────────────────────")
    lines.append(f"  Total today:  ${total:.4f}")
    lines.append(f"  Remaining:    ${remaining:.4f}")
    return "\n".join(lines)


def full_history() -> str:
    """Summary of all spending by day."""
    log = _load()
    if not log:
        return "No spending recorded yet."
    lines = ["Spending history:"]
    for day in sorted(log.keys(), reverse=True):
        total = sum(s.get("cost", 0) for s in log[day].values())
        lines.append(f"  {day}  ${total:.4f}")
    return "\n".join(lines)
