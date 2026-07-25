"""
Team seats — let a paid owner share their ARIA plan with a limited number of
human members (distinct from ``team.py``, which is the roster of AI specialists).

Model (stored in the shared cache):
  aria:seats:team:{owner}    -> {"members": [email, ...]}
  aria:seats:member_of:{email} -> owner_email   (reverse index, one team per email)

A member inherits the owner's *current* plan (resolved live from the owner's
plan record, not a frozen copy) so that if the owner downgrades or cancels, the
members lose the shared access automatically. Seat limits come from the plan's
``seats`` field, passed in by the caller (main.py owns the plan catalog).

All functions fail safe: on a cache error they behave as "no team" rather than
granting or wrongly denying access.
"""

from __future__ import annotations

_TEAM_KEY = "aria:seats:team:{owner}"
_MEMBER_KEY = "aria:seats:member_of:{email}"
_TTL = 400 * 24 * 3600  # long-lived; refreshed on every write


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


async def _cache():
    from apps.core.memory.redis_client import get_cache

    return get_cache()


async def list_members(owner: str) -> list[str]:
    """Emails the owner has added to their team (excludes the owner)."""
    owner = norm_email(owner)
    if not owner:
        return []
    try:
        rec = await (await _cache()).get(_TEAM_KEY.format(owner=owner))
        members = (rec or {}).get("members", []) if isinstance(rec, dict) else []
        return [m for m in members if m and m != owner]
    except Exception:
        return []


async def owner_of(email: str) -> str | None:
    """The owner whose team this email belongs to, or None."""
    email = norm_email(email)
    if not email:
        return None
    try:
        owner = await (await _cache()).get(_MEMBER_KEY.format(email=email))
        return owner or None
    except Exception:
        return None


async def add_member(owner: str, member: str, seats: int) -> tuple[bool, str]:
    """Invite ``member`` to ``owner``'s team. Returns (ok, message).

    ``seats`` is the plan's seat allowance INCLUDING the owner, so the number of
    additional members is ``seats - 1``. Enforces the seat cap and prevents a
    member from belonging to two teams or an owner from adding themselves.
    """
    owner = norm_email(owner)
    member = norm_email(member)
    if not owner or not member:
        return False, "Missing email."
    if "@" not in member or "." not in member.split("@")[-1]:
        return False, "That doesn't look like a valid email."
    if member == owner:
        return False, "You're already the owner of this workspace."
    if seats <= 1:
        return False, "Your plan doesn't include extra seats. Upgrade to add members."

    try:
        cache = await _cache()
        existing_owner = await owner_of(member)
        if existing_owner and existing_owner != owner:
            return False, "That person is already a member of another ARIA workspace."

        rec = await cache.get(_TEAM_KEY.format(owner=owner))
        members = list((rec or {}).get("members", [])) if isinstance(rec, dict) else []
        members = [m for m in members if m and m != owner]
        if member in members:
            return True, "They're already on your team."
        # seats includes the owner, so allowed extra members = seats - 1.
        if len(members) >= max(0, seats - 1):
            return False, f"You've used all {seats} seats. Remove a member or upgrade."

        members.append(member)
        await cache.set(_TEAM_KEY.format(owner=owner), {"members": members}, ttl_seconds=_TTL)
        await cache.set(_MEMBER_KEY.format(email=member), owner, ttl_seconds=_TTL)
        return True, f"Added {member} to your team."
    except Exception:
        return False, "Couldn't update your team right now. Please try again."


async def remove_member(owner: str, member: str) -> bool:
    owner = norm_email(owner)
    member = norm_email(member)
    if not owner or not member:
        return False
    try:
        cache = await _cache()
        rec = await cache.get(_TEAM_KEY.format(owner=owner))
        members = list((rec or {}).get("members", [])) if isinstance(rec, dict) else []
        members = [m for m in members if m and m != member and m != owner]
        await cache.set(_TEAM_KEY.format(owner=owner), {"members": members}, ttl_seconds=_TTL)
        # Only clear the reverse index if it still points at this owner.
        if (await owner_of(member)) == owner:
            await cache.set(_MEMBER_KEY.format(email=member), "", ttl_seconds=1)
        return True
    except Exception:
        return False
