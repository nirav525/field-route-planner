"""A local spending stop for the note reader, so a key can't run up a surprise bill.

It counts what this app has spent, using the token counts the API returns. It can't see
other apps using the same key, so a workspace limit in the Anthropic Console is still the real cap.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SPEND_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_spend.json"
LIMIT_USD = float(os.environ.get("ROUTE_PLANNER_BUDGET_USD", "5.00"))

# Claude Opus 5.5 prices per million tokens. Other models are counted at these rates too.
INPUT_USD_PER_M = 4.00
OUTPUT_USD_PER_M = 20.00

MAX_OUTPUT_TOKENS = 4000
MAX_NOTE_CHARS = 2000
# Most one call can cost: full output, plus a generous bound on input (notes, prompt, id lists).
WORST_CASE_CALL_USD = (MAX_OUTPUT_TOKENS * OUTPUT_USD_PER_M + 3000 * INPUT_USD_PER_M) / 1_000_000


def spent(path: Path = SPEND_PATH) -> float:
    try:
        return float(json.loads(path.read_text())["usd"])
    except FileNotFoundError:
        return 0.0
    except (ValueError, KeyError, TypeError):
        return LIMIT_USD  # a damaged record stops spending rather than resetting it to zero


def can_spend(path: Path = SPEND_PATH, limit: float | None = None) -> bool:
    """Stops before a call that could cross the limit, not after."""
    return spent(path) + WORST_CASE_CALL_USD <= (LIMIT_USD if limit is None else limit)


def record(usage, path: Path = SPEND_PATH) -> None:
    if usage is None:
        return
    cost = (usage.input_tokens * INPUT_USD_PER_M + usage.output_tokens * OUTPUT_USD_PER_M) / 1_000_000
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"usd": round(spent(path) + cost, 6)}))
