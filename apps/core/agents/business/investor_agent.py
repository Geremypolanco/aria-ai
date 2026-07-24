"""
Investor Agent — Fundraising, outreach to VCs/Angels, and pitch decks.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent

logger = logging.getLogger("aria.business.investor")


class InvestorAgent(BaseAgent):
    IDENTITY = (
        "You are ARIA AI's Investor Agent. Your mission is to secure real capital for the project. "
        "You identify angel investors, VCs, and strategic partners. You write irresistible pitches "
        "and run outreach campaigns on LinkedIn and email. "
        "You don't ask for permission, you go after real money. You are aggressive, direct, and results-focused. "
        "You make sure Aria's value is obvious to any serious investor."
    )

    def __init__(self) -> None:
        super().__init__(
            name="investor",
            description="Fundraising, investor outreach, pitch decks, and equity management",
            capabilities=[
                "investor_research",
                "outreach",
                "pitch_decks",
                "linkedin_networking",
            ],
        )

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        mission = context.get("mission", "Find investors for Aria AI")
        niche = context.get("niche", "AI SaaS / E-commerce")
        target_amount = context.get("target_amount", "$100k - $500k")

        results: dict[str, Any] = {"success": True, "agent": "investor", "mission": mission}

        # 1. Research potential investors
        investors = await self._research_investors(niche)
        results["potential_investors"] = investors

        # 2. Generate Pitch and Outreach
        pitches = await self._generate_pitches(investors, target_amount)
        results["outreach_campaign"] = pitches

        # 3. Execute Outreach if enabled — ALWAYS requires explicit human
        # approval: _research_investors() is not real-time research (see its
        # docstring), so automatic outreach would send personalized messages
        # targeting real firms (Sequoia, Y Combinator, etc.) drafted from a
        # fixed example list, not real verification. This never
        # auto-approves regardless of `auto_outreach` — the owner must
        # confirm via Telegram.
        if context.get("auto_outreach", False):
            approval = await self.request_human_approval(
                action="Send investment outreach on LinkedIn",
                details=(
                    f"Pitches ready for: {', '.join(p['investor'] for p in pitches)}. "
                    "Note: the investor list is a reference example, not "
                    "verified research — review the content before approving."
                ),
            )
            if approval.get("success") and approval.get("status") != "pending":
                outreach_results = await self._execute_outreach(pitches)
                results["outreach_results"] = outreach_results
            else:
                results["outreach_results"] = approval

        results["summary"] = f"Found {len(investors)} potential investors. Outreach campaign ready."
        return results

    async def _research_investors(self, niche: str) -> list[dict]:
        """Example placeholder — NOT real or verified research.

        This used to be returned as if it were the result of a search,
        with real firm names (Sequoia, Y Combinator...), and was used to
        generate pitches personalized to those firms by name. _execute()
        now blocks any real outreach behind explicit human approval
        precisely because this data is not verified research — see the
        note in request_human_approval().
        """
        # In a real run, this would call AriaMind.execute_tool("web_search", ...)
        return [
            {
                "name": "TechStars AI",
                "type": "Accelerator",
                "focus": "AI/ML",
                "verified": False,
            },
            {
                "name": "Y Combinator",
                "type": "Accelerator",
                "focus": "General Tech",
                "verified": False,
            },
            {
                "name": "Sequoia Capital",
                "type": "VC",
                "focus": "High Growth",
                "verified": False,
            },
            {
                "name": "AngelList AI Syndicate",
                "type": "Angel Group",
                "focus": "Early Stage AI",
                "verified": False,
            },
        ]

    async def _generate_pitches(self, investors: list[dict], amount: str) -> list[dict]:
        pitches = []
        for inv in investors:
            pitch = await self.think(
                system=self.IDENTITY,
                user=f"Write a personalized LinkedIn message for {inv['name']} ({inv['type']}). "
                f"We're seeking {amount} to scale Aria AI, an autonomous AI focused on generating "
                f"revenue on Shopify. Don't make up traction figures, customers, or specific revenue — "
                f"if you don't have verified data on hand, talk about the product and the vision without "
                f"claiming unconfirmed concrete metrics.",
            )
            pitches.append({"investor": inv["name"], "pitch": pitch})
        return pitches

    async def _execute_outreach(self, pitches: list[dict]) -> dict:
        """Executes posting on LinkedIn or sending messages."""
        from apps.core.tools.social_media import SocialMediaManager

        sm = SocialMediaManager()
        results = []
        for p in pitches:
            # Send as a post or private message if the API allows it
            res = await sm.post_content("linkedin", p["pitch"])
            results.append({"investor": p["investor"], "status": res})
        return {"sent_count": len(results), "details": results}
