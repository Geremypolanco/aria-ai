"""
Owner alerts: real-time email notifications for the three events the owner
asked to be told about directly (first login, plan purchased, subscription
canceled), plus a weekly digest built from the same real, already-tracked
funnel counters (apps/core/main.py's TRACK_EVENTS) — never fabricated
numbers, and never a second parallel analytics system.

Sends through PublishingTools.send_newsletter — the same real provider
stack (Resend -> SendGrid -> Mailgun) already used by aria_mind.py's
send_email tool and apps/acquisition/delivery/delivery_engine.py, so an
owner alert goes out over the same audited path, not a new bespoke sender.

Destination is apps.core.auth.owner_emails() — the single source of truth
for "who is the owner" already used to gate /admin and other owner-only
capabilities — rather than a second hardcoded email living here that could
drift out of sync with that one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("aria.notifications.owner_alerts")

# Must match apps/core/main.py's TRACK_EVENTS tuple (funnel counters this
# module reads back out for the weekly digest) plus the three events this
# module itself records on the notification hooks below. Duplicated here
# rather than imported to avoid main.py <-> this module import ordering.
_FUNNEL_EVENTS = (
    "landing_view",
    "signup_page_view",
    "signup_submitted",
    "login_submitted",
    "auth_success",
    "checkout_started",
    "checkout_agreed",
    "first_login",
    "plan_purchased",
    "subscription_canceled",
)

_WEEKLY_REPORT_LAST_SENT_KEY = "aria:weekly_report:last_sent"
_REPORT_INTERVAL_SECONDS = 7 * 86400
_LOOP_CHECK_INTERVAL_SECONDS = 3600  # hourly — cheap, and see the docstring
# on weekly_report_loop() for why this can't just be asyncio.sleep(7 days).


async def notify_owner(subject: str, body: str) -> None:
    """Best-effort email to the owner. Never raises — a notification
    failure must never break the login/checkout/webhook flow that
    triggered it."""
    try:
        from apps.core import auth
        from apps.core.tools.publishing_tools import PublishingTools

        to = next(iter(auth.owner_emails()), None)
        if not to:
            return
        result = await PublishingTools().send_newsletter(subject, body, to_override=to)
        if not result.get("success"):
            logger.warning("notify_owner('%s') send failed: %s", subject, result.get("error"))
    except Exception as exc:
        logger.warning("notify_owner('%s') failed: %s", subject, exc)


async def _track(event: str) -> None:
    """Same lifetime+today counter increment as main.py's _track(), so
    first_login/plan_purchased/subscription_canceled show up in the
    existing /admin funnel view and this module's own weekly rollup for
    free — duplicated rather than imported for the same reason as
    _FUNNEL_EVENTS above."""
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        await cache.increment(f"aria:track:{event}:total")
        await cache.increment(f"aria:track:{event}:{today}")
    except Exception as exc:
        logger.warning("_track('%s') failed: %s", event, exc)


async def _track_revenue(amount_usd: float) -> None:
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        await cache.increment_by(f"aria:track:revenue_usd:{today}", amount_usd)
    except Exception as exc:
        logger.warning("_track_revenue failed: %s", exc)


async def notify_first_login(email: str, name: str = "", provider: str = "") -> None:
    """Fires exactly once per email, ever — regardless of which login path
    (email signup, email login, Google/GitHub OAuth) got there first. Uses
    an atomic create-only Redis write so two near-simultaneous requests for
    the same brand-new email can't both fire the notification."""
    if not email:
        return
    try:
        from apps.core.memory.redis_client import get_cache

        cache = get_cache()
        is_first = await cache.set_if_not_exists(
            f"aria:notified:first_login:{email.strip().lower()}",
            "1",
            ttl_seconds=86400 * 3650,
        )
    except Exception as exc:
        logger.warning("notify_first_login idempotency check failed: %s", exc)
        return
    if not is_first:
        return

    await _track("first_login")
    who = f"{name} ({email})" if name else email
    await notify_owner(
        f"New customer: {who}",
        f"{who} just logged in for the first time" + (f" via {provider}." if provider else "."),
    )


async def notify_plan_purchased(email: str, tier: str, amount_usd: float) -> None:
    if not email:
        return
    await _track("plan_purchased")
    await _track_revenue(amount_usd)
    await notify_owner(
        f"New payment: {email} — ${amount_usd:,.2f}",
        f"{email} just paid ${amount_usd:,.2f} for the {tier} plan.",
    )


async def notify_subscription_canceled(email: str) -> None:
    if not email:
        return
    await _track("subscription_canceled")
    await notify_owner(
        f"Subscription canceled: {email}",
        f"{email} canceled their subscription.",
    )


# ── Weekly digest ────────────────────────────────────────────────────────


async def _weekly_rollup() -> dict[str, int]:
    """Sums each funnel event's daily counters over the trailing 7 calendar
    days (today inclusive) — the same per-day keys main.py's _track()
    already writes, just read back over a week instead of one day."""
    from apps.core.memory.redis_client import get_cache

    cache = get_cache()
    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    totals: dict[str, int] = dict.fromkeys(_FUNNEL_EVENTS, 0)
    for event in _FUNNEL_EVENTS:
        for day in days:
            with suppress(Exception):
                totals[event] += int(await cache.get(f"aria:track:{event}:{day}") or 0)

    revenue = 0.0
    for day in days:
        with suppress(Exception):
            revenue += float(await cache.get(f"aria:track:revenue_usd:{day}") or 0.0)
    totals["_revenue_usd"] = revenue
    return totals


def _diagnose(weekly: dict[str, int]) -> str:
    """One honest, specific bottleneck call-out grounded entirely in the
    numbers already in this same report — never a second set of invented
    figures. Picks the single biggest drop-off point, the same
    find_growth_bottleneck philosophy used elsewhere in this codebase,
    rather than listing every possible observation."""
    if weekly["landing_view"] == 0:
        return (
            "Nobody visited the landing page at all this week. That's a traffic-"
            "acquisition problem (SEO, social, ads) — nothing on the site itself "
            "can convert a visitor who never arrives."
        )
    if weekly["signup_page_view"] == 0:
        return (
            f"{weekly['landing_view']} landing page view(s) but zero people reached "
            "the signup page — check that the primary call-to-action is visible and "
            "actually links to /signup."
        )
    if weekly["signup_submitted"] == 0:
        return (
            f"{weekly['signup_page_view']} visit(s) to the signup page but nobody "
            "submitted it — likely friction in the form itself, or visitors aren't "
            "convinced yet by the time they get there."
        )
    if weekly["auth_success"] == 0 and weekly["first_login"] == 0:
        return (
            f"{weekly['signup_submitted']} signup attempt(s) but none resulted in a "
            "successful login — check for signup errors (duplicate email, "
            "validation failures)."
        )
    if weekly["checkout_started"] == 0:
        return (
            f"{weekly['first_login']} new first-time login(s) this week but nobody "
            "started checkout — the pricing/upgrade path may not be visible enough "
            "inside the app."
        )
    if weekly["plan_purchased"] == 0:
        return (
            f"{weekly['checkout_started']} checkout(s) started but zero completed "
            "payments — check Stripe for declined cards or an unclear price at "
            "the final step."
        )
    if (
        weekly["subscription_canceled"] > 0
        and weekly["subscription_canceled"] >= weekly["plan_purchased"]
    ):
        return (
            f"{weekly['subscription_canceled']} cancellation(s) this week versus "
            f"{weekly['plan_purchased']} new paid plan(s) — churn matched or "
            "outpaced new revenue; worth finding out why canceling customers left."
        )
    return (
        f"{weekly['plan_purchased']} paid plan(s) and ${weekly['_revenue_usd']:,.2f} in "
        "revenue this week, with no single obvious blocked step in the funnel above "
        "— the next lever is more volume into the top of the funnel that's already "
        "converting."
    )


async def build_weekly_report() -> str:
    weekly = await _weekly_rollup()
    lines = [
        "Weekly report",
        "",
        f"Landing page views: {weekly['landing_view']}",
        f"Signup page views: {weekly['signup_page_view']}",
        f"Signups submitted: {weekly['signup_submitted']}",
        f"First-time logins: {weekly['first_login']}",
        f"Checkouts started: {weekly['checkout_started']}",
        f"Plans purchased: {weekly['plan_purchased']}",
        f"Subscriptions canceled: {weekly['subscription_canceled']}",
        f"Revenue: ${weekly['_revenue_usd']:,.2f}",
        "",
        "What to improve:",
        _diagnose(weekly),
    ]
    return "\n".join(lines)


async def send_weekly_report() -> None:
    body = await build_weekly_report()
    await notify_owner("Your weekly report", body)


async def _check_and_maybe_send_weekly_report() -> bool:
    """One check: send the weekly report iff 7+ days have passed since the
    last confirmed send (persisted in Redis, not process memory). Returns
    True iff it actually sent. Split out from weekly_report_loop() so a test
    can exercise one check deterministically instead of running the
    infinite loop."""
    from apps.core.memory.redis_client import get_cache

    cache = get_cache()
    last_sent_raw = await cache.get(_WEEKLY_REPORT_LAST_SENT_KEY)
    last_sent = float(last_sent_raw) if last_sent_raw else 0.0
    if time.time() - last_sent < _REPORT_INTERVAL_SECONDS:
        return False
    await send_weekly_report()
    await cache.set(_WEEKLY_REPORT_LAST_SENT_KEY, str(time.time()), ttl_seconds=86400 * 3650)
    return True


async def weekly_report_loop() -> None:
    """Runs for the lifetime of the process, checking hourly (not sleeping
    for 7 days straight) whether a week has actually elapsed since the last
    report — because deploy.yml redeploys on every merge to main, an
    in-process asyncio.sleep(7 days) would almost never survive long enough
    to fire (the same restart-survival problem PR #153 already fixed for
    the income loop). The "last sent" timestamp is persisted in Redis, so
    this picks up correctly across any number of restarts in between."""
    while True:
        try:
            await _check_and_maybe_send_weekly_report()
        except Exception as exc:
            logger.warning("weekly_report_loop iteration failed: %s", exc)
        await asyncio.sleep(_LOOP_CHECK_INTERVAL_SECONDS)
