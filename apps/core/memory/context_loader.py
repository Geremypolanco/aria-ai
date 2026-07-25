"""
context_loader.py — the single place that decides what ARIA "remembers"
about a user before it answers them.

Called by apps/core/main.py's HTTP (/api/v1/chat) and WebSocket (/ws/chat)
entrypoints, right before AriaMind.handle() builds its prompt. Combines two
sources, both scoped to the same user:

  - episodic_memory.recall()  — past conversation snippets ("what happened")
  - user_facts.recall()       — durable facts/preferences ("what ARIA knows
    about this person specifically")

Isolation: this function accepts a single `email` string and nothing else —
there is no code path here that can fetch more than one user's memory,
because neither underlying recall() call accepts a list or a wildcard. A
falsy `email` returns "" immediately: there's no sensible memory to load for
an anonymous request, and no fallback that could risk mixing in someone
else's.

Both HTTP and WS chat entrypoints must call this before AriaMind.handle() —
previously only the HTTP path did (a real gap: WebSocket users got no
long-term memory injection at all), which is why this was pulled out into
one shared function instead of copy-pasted a second time.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("aria.context_loader")


async def load_user_context(email: str, query: str) -> str:
    email = (email or "").strip().lower()
    if not email:
        return ""

    from apps.core.cognition.episodic_memory import get_episodic_memory
    from apps.core.memory.user_facts import get_user_facts

    episodes, facts = await asyncio.gather(
        get_episodic_memory().recall(email, query, n=4),
        get_user_facts().recall(email, query, top_k=5),
        return_exceptions=True,
    )

    if isinstance(episodes, BaseException):
        logger.warning("[ContextLoader] episodic recall failed (non-fatal): %s", episodes)
        episodes = []
    if isinstance(facts, BaseException):
        logger.warning("[ContextLoader] fact recall failed (non-fatal): %s", facts)
        facts = []

    blocks = []
    fact_lines = "\n".join(f"- {f['content']}" for f in facts if f.get("content"))
    if fact_lines:
        blocks.append(f"[What I remember about this user:\n{fact_lines}]")
    ep_lines = "\n".join(f"- {e['content']}" for e in episodes if e.get("content"))
    if ep_lines:
        blocks.append(f"[From earlier sessions with this user:\n{ep_lines}]")

    return "\n\n".join(blocks)
