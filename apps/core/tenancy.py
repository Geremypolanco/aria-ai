"""
apps/core/tenancy.py — resolves which workspace a user's business data
belongs to.

The product's actual model (confirmed by apps/core/seats.py, the Business/
Scale team-seats feature) is that a team is ONE tenant: a plan owner and
every member they've added share one business — one Shopify store, one
cashflow ledger, one income loop. That's a deliberate product decision, not
a bug. What's been missing is that the storage layer never expressed it:
modules like apps/business/finance/cashflow_engine.py persisted to a single
hardcoded global Redis key instead of one key per workspace, so today there
is exactly one workspace across the entire deployment regardless of how
many teams sign up.

workspace_id_for() is the single place that answers "which workspace does
this user belong to" — every per-workspace store (cashflow, ROI, Shopify
automation state, the income loop, ...) should key its state off this
return value instead of a bare constant, one module at a time (see
apps/business/finance/cashflow_engine.py for the reference conversion).
"""

from __future__ import annotations


async def workspace_id_for(email: str) -> str:
    """The workspace identity for `email`: the team owner's email if
    `email` is a member of somebody else's team (apps/core/seats.py), else
    `email` itself — a solo user, or a team owner, is their own workspace.
    Returns "" for a blank/invalid email, same as seats.norm_email()."""
    from apps.core import seats

    email = seats.norm_email(email)
    if not email:
        return ""
    owner = await seats.owner_of(email)
    return owner or email
