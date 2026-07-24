"""
ARIA's team of AI professionals.

Each professional is a persona layered on ARIA's real cognitive + tool engine:
picking one injects that specialist's identity and working style, so the same
underlying ARIA answers as (and works like) a dedicated Content Strategist,
Copywriter, Lawyer, Accountant, etc. — a full, department-structured team you
can put to work on an objective.

The roster itself is data, loaded from ``team_data.json`` (kept as JSON so the
long persona/résumé text stays free of Python-escaping pitfalls). The persona
string is prepended to the user context on the chat/workflow path so the model
adopts the role. Avatars are served from /team/<id>.png; when a portrait has not
been generated yet the client falls back to a clean initials avatar.

Each member carries a professional profile — a résumé, a cover letter and a
track record of headline stats. These specialists are AI personas, so those
profiles are illustrative character content (the way a studio writes a bio for a
character), not audited results for named clients, and the client surfaces them
with that "illustrative profile" framing.

Regulated-advice roles (Legal & Compliance, and the Accountant / Financial
Analyst) carry an explicit, honest boundary in their persona and cover letter:
they help you draft, review, research and understand documents and work
alongside your own licensed professional, but are not a substitute for a
licensed attorney / accountant and do not provide legal, tax or investment
advice.
"""

from __future__ import annotations

import json
import os
from typing import Any

_DATA_PATH = os.path.join(os.path.dirname(__file__), "team_data.json")

# Department display order in the dashboard.
DEPARTMENTS: list[str] = [
    "Content & Creative",
    "Marketing & Growth",
    "Research & Data",
    "Engineering & Product",
    "Legal & Compliance",
    "Finance & Operations",
    "Sales & Customer Success",
]


def _load_team() -> list[dict[str, Any]]:
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


TEAM: list[dict[str, Any]] = _load_team()

_BY_ID = {m["id"]: m for m in TEAM}


def get_member(member_id: str) -> dict[str, Any] | None:
    return _BY_ID.get((member_id or "").strip().lower())


def _public_card(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": m["id"],
        "name": m["name"],
        "title": m["title"],
        "department": m.get("department", ""),
        "specialty": m["specialty"],
        "avatar": f"/team/{m['id']}.png",
        "metrics": m.get("metrics", []),
    }


def public_team() -> list[dict[str, Any]]:
    """Flat roster for the client — no persona internals."""
    return [_public_card(m) for m in TEAM]


def public_team_grouped() -> list[dict[str, Any]]:
    """Roster grouped by department, in DEPARTMENTS order.

    Any department not listed in DEPARTMENTS is appended at the end so nothing
    silently disappears if a new one is added to the data.
    """
    order = {d: i for i, d in enumerate(DEPARTMENTS)}
    groups: dict[str, list[dict[str, Any]]] = {}
    for m in TEAM:
        groups.setdefault(m.get("department", "Other"), []).append(_public_card(m))
    ordered = sorted(groups.items(), key=lambda kv: order.get(kv[0], len(order)))
    return [{"department": dept, "members": members} for dept, members in ordered]


def member_profile(member_id: str) -> dict[str, Any] | None:
    """Full public profile for one member — résumé, cover letter, metrics.

    No persona internals. Metrics/résumé are illustrative character content for
    an AI persona; the ``illustrative`` flag lets the client label them honestly.
    """
    m = get_member(member_id)
    if not m:
        return None
    return {
        "id": m["id"],
        "name": m["name"],
        "title": m["title"],
        "department": m.get("department", ""),
        "specialty": m["specialty"],
        "avatar": f"/team/{m['id']}.png",
        "resume": m.get("resume", {}),
        "cover_letter": m.get("cover_letter", ""),
        "metrics": m.get("metrics", []),
        "illustrative": True,
    }


def persona_context(member_id: str) -> str:
    """The instruction prepended to the user context so ARIA works AS this pro."""
    m = get_member(member_id)
    if not m:
        return ""
    return (
        f"[Act as {m['name']}, ARIA's {m['title']}. {m['persona']} "
        f"Stay in your specialty and deliver the finished work.]"
    )
