"""Rough token estimation for cost guardrails (NFR-10).

Not a real tokenizer — a ~4-chars-per-token heuristic is good enough to
flag oversized requests and to log an approximate token count.
"""

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)
