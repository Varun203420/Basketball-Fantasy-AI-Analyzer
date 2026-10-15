"""Claude explanations. The engine has already ranked the players; Claude only explains.

Needs ANTHROPIC_API_KEY in .env at the repo root. The model can be changed with
ANTHROPIC_MODEL (a fast model is better under a pick clock).
"""
import os

DEFAULT_MODEL = "claude-haiku-5-5"

SYSTEM = (
    "You are a fantasy basketball draft assistant. A stats engine has already ranked "
    "the options; never re-rank them or invent stats. In under 120 words, explain "
    "which of the top options to take and why, mention the main tradeoff, and note "
    "any player likely to be gone before our next pick. Be direct."
)


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def explain_pick(context: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL),
        max_tokens=300,
        system=SYSTEM,
        messages=[{"role": "user", "content": context}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")
