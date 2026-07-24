"""
ecommerce_agent.py — Specialized E-commerce and High-Ticket Sales Agent v1.0

This agent is the brain of Aria's e-commerce operations.
Its responsibilities are:
1. Research Shopify, Zapier, and e-commerce best practices on the web.
2. Create complete products (listing, inventory, images, videos) on Shopify.
3. Design and execute sales funnels for high-value (High-Ticket) services.
4. Automate workflows between Shopify and other apps via Zapier (MCP).
5. Continuously learn from market trends to optimize the store.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.agents.base_agent import BaseAgent
from apps.core.config import settings
from apps.core.tools.ai_client import AIModel, get_ai_client
from apps.core.tools.aria_tools import tool_registry

logger = logging.getLogger("aria.ecommerce_agent")


# ── BUILT-IN E-COMMERCE KNOWLEDGE ─────────────────────────────────────

ECOMMERCE_KNOWLEDGE = {
    "shopify_listing_best_practices": [
        "SEO title: include the main keyword, brand, and key attribute (color, material, size).",
        "Persuasive HTML description: use the AIDA format (Attention, Interest, Desire, Action).",
        "Images: minimum 3-5 high-resolution photos (white background + lifestyle). Alt text with keywords.",
        "Competitive price: research competitors before setting a price. Show the original price struck through.",
        "Inventory: always manage it with Shopify to avoid overselling.",
        "Tags: include 10-15 relevant tags for internal search and marketing apps.",
        "SEO metafields: optimize SEO title (max 70 chars) and meta description (max 160 chars).",
        "Structured data: make sure the theme includes Product schema for Google Shopping.",
        "Reviews: set up a reviews app (Judge.me, Yotpo) to generate social proof.",
        "Collections: organize products into logical collections to improve navigation.",
    ],
    "zapier_shopify_automations": [
        "New Order → Slack/Gmail: notify the team of every sale in real time.",
        "New Customer → Mailchimp/Klaviyo: add to the email marketing list (with consent).",
        "Inventory Updated → Gmail: alert when stock drops below the minimum threshold.",
        "Abandoned Cart → Gmail/SMS: send a personalized reminder at 1h, 24h, and 72h.",
        "New Order → Google Sheets: log sales for analysis and automatic reports.",
        "New Customer → HubSpot: create a CRM contact for follow-up.",
        "Quiz/Form Submission → OpenAI → Gmail: personalized AI-powered product consultation.",
        "New Paid Order → Typeform: send a post-purchase satisfaction survey.",
        "Product Back in Stock → Email List: notify interested customers.",
        "New Order → Airtable: sync data for operations management.",
    ],
    "high_ticket_sales_strategies": [
        "Qualification: use an application form to filter serious prospects before investing time.",
        "Authority positioning: publish success stories, testimonials, and quantifiable results.",
        "Sell transformation, not price: focus on the ROI and life change the client will get.",
        "Consultative process: act as an expert advisor, not a salesperson. Listen more than talk.",
        "Unique value proposition: clearly differentiate from the competition with guarantees and bonuses.",
        "Value follow-up: send useful resources (articles, videos, success stories) between contacts.",
        "Real urgency: use genuine deadlines and limited slots, not artificial ones.",
        "Anchor pricing: show the total value of the service before revealing the real price.",
        "Results guarantee: offer a money-back guarantee to reduce perceived risk.",
        "Premium onboarding: the client onboarding process must be flawless and memorable.",
    ],
    "product_research_framework": [
        "Analyze trends on Google Trends, Amazon Best Sellers, and TikTok Shop.",
        "Validate demand with keyword research (Ahrefs, SEMrush, Google Keyword Planner).",
        "Study competitors' negative reviews to identify market gaps.",
        "Calculate margins: selling price must be at least 3x the cost (the 3x rule).",
        "Check restrictions: avoid products with patents, regulations, or heavy competition.",
        "Evaluate upsell potential: products with recurring accessories or consumables.",
        "Analyze seasonality to plan inventory and marketing campaigns.",
    ],
    "content_for_ecommerce": [
        "Product videos: show the product in use, unboxing, and comparisons (30-90 seconds).",
        "Lifestyle photos: show the product in a real context with models or aspirational settings.",
        "Infographics: highlight technical features in a visual, easy-to-understand way.",
        "User Generated Content (UGC): encourage customers to share photos/videos using the product.",
        "Buying guides: create educational content that positions Aria as an expert in the niche.",
        "Comparisons: 'Product A vs Product B' articles to capture search traffic.",
    ],
}


class EcommerceAgent(BaseAgent):
    """
    Agent specialized in e-commerce, Shopify, Zapier, and High-Ticket sales.
    Continuously learns from the web and performs real operations on Shopify.
    """

    def __init__(self) -> None:
        super().__init__(
            name="ecommerce",
            description="E-commerce agent: Shopify, Zapier, listings, inventory, and High-Ticket",
            capabilities=[
                "shopify_product_creation",
                "listing_optimization",
                "inventory_management",
                "zapier_automation",
                "high_ticket_sales",
                "market_research",
                "content_creation",
                "landing_page_generation",
            ],
        )
        self.knowledge = ECOMMERCE_KNOWLEDGE
        self._zapier = None  # Zapier disabled at the user's request
        self._web = tool_registry.get_tool("web_scraping")

    async def _execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Runs the e-commerce mission based on the given context."""
        task = context.get("task", "full_ecommerce_pipeline")
        topic = context.get("target_topic", "high-value products")

        logger.info(f"[EcommerceAgent] Starting task: {task} | Topic: {topic}")

        if task == "research_and_create_product":
            return await self._research_and_create_product(topic)
        if task == "optimize_store":
            return await self._optimize_store()
        if task == "setup_zapier_automations":
            return await self._setup_zapier_automations()
        if task == "high_ticket_funnel":
            return await self._create_high_ticket_funnel(topic)
        if task == "create_landing_page":
            return await self._create_landing_page(topic, context.get("description", ""))
        if task == "full_ecommerce_pipeline":
            return await self._full_ecommerce_pipeline(topic)
        return await self._full_ecommerce_pipeline(topic)

    # ── FULL PIPELINE ─────────────────────────────────────────

    async def _full_ecommerce_pipeline(self, topic: str) -> dict[str, Any]:
        """
        Full e-commerce pipeline (Claude Code Protocol):
        1. Verify deliverability (Don't sell the impossible).
        2. Research market trends and opportunities.
        3. Generate a product idea with AI.
        4. Create an optimized listing on Shopify.
        5. Set up Zapier automations.
        6. Create a High-Ticket sales funnel.
        """
        results = {}

        # Step 0: Deliverability check (bilingual match against user topic — left untranslated)
        is_physical = any(
            k in topic.lower() for k in ["casa", "físico", "hardware", "gadget", "envío"]
        )
        if is_physical and "digital" not in topic.lower():
            return {
                "success": False,
                "error": f"Mission aborted: I can't sell '{topic}' because it's a physical product and Aria only operates with digital assets or verifiable services.",
                "agent": "ecommerce",
            }

        # Step 1: Research the market
        market_data = await self._research_market(topic)
        results["market_research"] = market_data

        # Step 2: Generate a product idea with AI
        product_idea = await self._generate_product_idea(topic, market_data)
        results["product_idea"] = product_idea

        # Step 3: Create the listing on Shopify (real production)
        if product_idea.get("title"):
            shopify_result = await self._create_shopify_listing(product_idea)
            results["shopify_listing"] = shopify_result

            # Take a screenshot of the created product if we have the URL
            if shopify_result.get("success") and shopify_result.get("product_url"):
                try:
                    from apps.core.tools.web_tools import WebTools

                    wt = WebTools()
                    ss_res = await wt.take_screenshot(shopify_result["product_url"])
                    if ss_res.get("success"):
                        results["product_screenshot"] = ss_res["screenshot_path"]
                except Exception as e:
                    logger.warning(f"[EcommerceAgent] Error taking screenshot: {e}")

        # Step 4: Set up Zapier (disabled)
        results["zapier_automations"] = {
            "success": True,
            "note": "Zapier temporarily disabled.",
        }

        # Step 5: High-Ticket strategy
        highticket_strategy = await self._create_high_ticket_funnel(topic)
        results["high_ticket_strategy"] = highticket_strategy

        results["success"] = True
        results["summary"] = f"E-commerce pipeline completed for: {topic}"
        return results

    # ── MARKET RESEARCH ──────────────────────────────────

    async def _research_market(self, topic: str) -> dict[str, Any]:
        """Researches trends, competitors, and opportunities on the web with screenshots."""
        logger.info(f"[EcommerceAgent] Researching market for: {topic}")

        research_data = {
            "topic": topic,
            "best_practices": self.knowledge["shopify_listing_best_practices"],
            "product_research_framework": self.knowledge["product_research_framework"],
            "screenshots": [],
        }

        # Try web search and screenshots if available
        if self._web:
            try:
                search_query = f"best shopify products to sell {topic} 2025 high demand"
                # We use the expanded search engine we implemented earlier
                from apps.core.tools.web_tools import WebTools

                wt = WebTools()
                search_results = await wt.search_web(search_query, num_results=3)

                if search_results.get("success") and search_results.get("results"):
                    research_data["web_findings"] = str(search_results["results"])

                    # Take a screenshot of the first relevant result (competitor)
                    top_url = search_results["results"][0].get("url")
                    if top_url:
                        ss_res = await wt.take_screenshot(top_url)
                        if ss_res.get("success"):
                            research_data["screenshots"].append(ss_res["screenshot_path"])
                            logger.info(
                                f"[EcommerceAgent] Competitor screenshot saved: {ss_res['screenshot_path']}"
                            )

            except Exception as e:
                logger.warning(f"[EcommerceAgent] Error researching with screenshots: {e}")

        return research_data

    async def _research_and_create_product(self, topic: str) -> dict[str, Any]:
        """Researches and creates a complete product on Shopify."""
        market_data = await self._research_market(topic)
        product_idea = await self._generate_product_idea(topic, market_data)

        if product_idea.get("title"):
            return await self._create_shopify_listing(product_idea)

        return {"success": False, "error": "Could not generate a valid product idea."}

    # ── AI PRODUCT GENERATION ────────────────────────────

    async def _generate_product_idea(
        self, topic: str, market_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Uses AI to generate a complete product idea optimized for Shopify."""
        ai = get_ai_client()
        if not ai:
            return self._fallback_product_idea(topic)

        system_prompt = (
            "You are an e-commerce and Shopify expert with 10 years of experience. "
            "Your specialty is creating product listings that convert and rank on Google. "
            "Respond ONLY with valid JSON, no markdown."
        )

        best_practices = "\n".join(
            f"- {p}" for p in self.knowledge["shopify_listing_best_practices"][:5]
        )

        user_prompt = f"""Create a complete, optimized Shopify listing about: "{topic}"

BEST PRACTICES TO APPLY:
{best_practices}

Generate the JSON with this exact format:
{{
  "title": "Optimized SEO title (max 70 chars, include the main keyword)",
  "description_html": "<p>Persuasive HTML description using the AIDA format. Minimum 200 words.</p>",
  "price": "price in USD as a string (e.g. '49.99')",
  "compare_at_price": "struck-through original price (e.g. '79.99')",
  "sku": "unique SKU code",
  "inventory": 50,
  "category": "product type",
  "vendor": "brand name",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "seo_title": "Title for Google (max 70 chars)",
  "seo_description": "Meta description for Google (max 160 chars)",
  "requires_shipping": true,
  "weight": 0.5,
  "weight_unit": "kg",
  "image_suggestions": ["image description 1", "image description 2", "image description 3"],
  "video_concept": "concept for a 30-60 second product video",
  "zapier_automations": ["recommended automation 1", "recommended automation 2"],
  "high_ticket_upsell": "description of a related premium service to sell for $500-$5000"
}}"""

        try:
            product = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.CREATIVE,
                max_tokens=1500,
                agent_name="ecommerce",
            )
            if product and product.get("title"):
                logger.info(f"[EcommerceAgent] Product generated: {product.get('title')}")
                return product
        except Exception as e:
            logger.error(f"[EcommerceAgent] Error generating product with AI: {e}")

        return self._fallback_product_idea(topic)

    def _fallback_product_idea(self, topic: str) -> dict[str, Any]:
        """Emergency plan for when the AI doesn't respond."""
        return {
            "title": f"Premium {topic} Product",
            "description_html": f"<p>Discover the best <strong>{topic}</strong> product. Premium quality guaranteed.</p>",
            "price": "99.99",
            "compare_at_price": "149.99",
            "sku": f"ARIA-{topic[:3].upper()}-001",
            "inventory": 50,
            "category": "General",
            "vendor": "Aria Premium",
            "tags": [topic, "premium", "quality", "deal", "new"],
            "seo_title": f"Buy {topic} Premium | Best Price",
            "seo_description": f"Find the best {topic} at the best price. Fast shipping and warranty included.",
            "requires_shipping": True,
            "image_suggestions": [
                "product photo on white background",
                "lifestyle photo in use",
                "quality detail shot",
            ],
            "video_concept": f"45-second video showing {topic} in use with customer testimonials",
            "zapier_automations": ["New Order → Slack notification", "New Customer → Mailchimp"],
            "high_ticket_upsell": f"Personalized {topic} consulting — $997/session",
        }

    # ── SHOPIFY LISTING CREATION ────────────────────────────

    async def _create_shopify_listing(self, product_data: dict[str, Any]) -> dict[str, Any]:
        """Creates a complete, optimized listing on Shopify."""
        try:
            from apps.core.integrations.shopify_engine import ShopifyEngine

            # Use the correct configuration variables for production
            shop_name = settings.SHOPIFY_URL or settings.SHOPIFY_SHOP_NAME
            access_token = settings.SHOPIFY_ADMIN_TOKEN or settings.SHOPIFY_ACCESS_TOKEN

            if not shop_name or not access_token:
                return {
                    "success": False,
                    "error": "Shopify credentials are not configured on the server.",
                }

            engine = ShopifyEngine(shop_name, access_token)
            product_id = engine.create_optimized_product(product_data)
            if product_id:
                # Use the same resolved shop_name as above — building this
                # from settings.SHOPIFY_SHOP_NAME directly produced
                # "https://None.myshopify.com/..." whenever only
                # SHOPIFY_URL was configured (the check a few lines up
                # already falls back to SHOPIFY_SHOP_NAME when needed).
                shop_url = f"https://{shop_name}.myshopify.com/products/"
                logger.info(f"[EcommerceAgent] Listing created on Shopify: {product_data['title']}")
                return {
                    "success": True,
                    "product_id": product_id,
                    "shop_url": shop_url,
                    "title": product_data["title"],
                    "price": product_data.get("price"),
                    "note": "Optimized listing created with SEO, inventory, and tags.",
                }
            return {"success": False, "error": "Could not create the product on Shopify"}
        except Exception as e:
            logger.error(f"[EcommerceAgent] Error creating Shopify listing: {e}")
            return {"success": False, "error": str(e)}

    async def _optimize_store(self) -> dict[str, Any]:
        """Analyzes and optimizes the existing Shopify store."""
        try:
            from apps.core.integrations.shopify_engine import ShopifyEngine

            shop_name = settings.SHOPIFY_URL or settings.SHOPIFY_SHOP_NAME
            access_token = (
                settings.SHOPIFY_ADMIN_TOKEN
                or settings.SHOPIFY_AUTOMATION_TOKEN
                or settings.SHOPIFY_ACCESS_TOKEN
            )
            engine = ShopifyEngine(shop_name, access_token)

            products = engine.get_all_products()
            orders_report = engine.get_orders_report()

            optimizations = []
            for product in products[:10]:
                issues = []
                if not product.get("images"):
                    issues.append("No images — add at least 3 high-quality photos")
                if len(product.get("tags", "")) < 20:
                    issues.append("Too few tags — add 10-15 relevant tags for SEO")
                if not product.get("body_html") or len(product.get("body_html", "")) < 200:
                    issues.append("Description too short — expand with benefits and keywords")
                if issues:
                    optimizations.append({"product": product.get("title"), "issues": issues})

            return {
                "success": True,
                "total_products": len(products),
                "revenue_report": orders_report,
                "optimization_recommendations": optimizations,
                "best_practices": self.knowledge["shopify_listing_best_practices"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── ZAPIER AUTOMATIONS ───────────────────────────────────

    async def _setup_zapier_automations(self) -> dict[str, Any]:
        """Sets up and documents Zapier automations for Shopify."""
        automations = self.knowledge["zapier_shopify_automations"]

        if self._zapier:
            try:
                # Try to list the available actions in Zapier via MCP
                result = await self._zapier.call_zapier_action("list_actions", {"app": "shopify"})
                logger.info(f"[EcommerceAgent] Zapier actions available: {result}")
                return {
                    "success": True,
                    "recommended_automations": automations,
                    "zapier_connection": result,
                    "note": "Zapier MCP connected. Set up the recommended Zaps in the Zapier dashboard.",
                }
            except Exception as e:
                logger.warning(f"[EcommerceAgent] Zapier MCP not available: {e}")

        return {
            "success": True,
            "recommended_automations": automations,
            "note": "Automations documented. Set up manually at zapier.com/apps/shopify/integrations",
        }

    # ── HIGH-TICKET FUNNEL ────────────────────────────────────────

    async def _create_high_ticket_funnel(self, topic: str) -> dict[str, Any]:
        """Designs a sales funnel for high-value services related to the topic."""
        ai = get_ai_client()
        if not ai:
            return self._fallback_high_ticket_funnel(topic)

        system_prompt = (
            "You are an expert in selling high-value (High-Ticket) services with experience "
            "in digital business, consulting, and premium coaching. "
            "Respond ONLY with valid JSON, no markdown."
        )

        strategies = "\n".join(f"- {s}" for s in self.knowledge["high_ticket_sales_strategies"][:5])

        user_prompt = f"""Design a High-Ticket sales funnel for services related to: "{topic}"

STRATEGIES TO APPLY:
{strategies}

Generate the JSON with this format:
{{
  "service_name": "premium service name",
  "price_range": "price range (e.g. $997 - $4,997)",
  "target_audience": "description of the ideal client",
  "value_proposition": "unique value proposition in 2 sentences",
  "funnel_stages": [
    {{"stage": "Awareness", "action": "what to do to attract leads"}},
    {{"stage": "Interest", "action": "how to generate interest"}},
    {{"stage": "Qualification", "action": "how to qualify prospects"}},
    {{"stage": "Proposal", "action": "how to present the proposal"}},
    {{"stage": "Close", "action": "recommended closing technique"}}
  ],
  "follow_up_sequence": ["message 1 (day 1)", "message 2 (day 3)", "message 3 (day 7)"],
  "shopify_integration": "how to integrate this service into the Shopify store",
  "zapier_automation": "recommended Zapier automation for this funnel"
}}"""

        try:
            funnel = await ai.complete_json(
                system=system_prompt,
                user=user_prompt,
                model=AIModel.STRATEGY,
                max_tokens=1200,
                agent_name="ecommerce",
            )
            if funnel and funnel.get("service_name"):
                logger.info(
                    f"[EcommerceAgent] High-Ticket funnel created: {funnel.get('service_name')}"
                )
                return {"success": True, "funnel": funnel}
        except Exception as e:
            logger.error(f"[EcommerceAgent] Error creating High-Ticket funnel: {e}")

        return self._fallback_high_ticket_funnel(topic)

    def _fallback_high_ticket_funnel(self, topic: str) -> dict[str, Any]:
        """Emergency funnel for when the AI doesn't respond."""
        return {
            "success": True,
            "funnel": {
                "service_name": f"Premium {topic} Consulting",
                "price_range": "$997 - $4,997",
                "target_audience": f"Entrepreneurs and businesses that need to master {topic}",
                "value_proposition": f"We transform your business with {topic} in 90 days or your money back.",
                "funnel_stages": [
                    {
                        "stage": "Awareness",
                        "action": "Publish educational content on LinkedIn and the blog",
                    },
                    {"stage": "Interest", "action": "Offer a free 60-minute webinar"},
                    {
                        "stage": "Qualification",
                        "action": "Application form with 5 key questions",
                    },
                    {
                        "stage": "Proposal",
                        "action": "30-min discovery call + personalized proposal",
                    },
                    {"stage": "Close", "action": "Assumptive Close with a results guarantee"},
                ],
                "follow_up_sequence": [
                    "Day 1: Send a relevant success story",
                    "Day 3: Share a free valuable resource",
                    "Day 7: 'Break-up' email with genuine urgency",
                ],
                "shopify_integration": "Create a service page on Shopify with an application button",
                "zapier_automation": "Form submission → Calendly → Gmail confirmation → HubSpot CRM",
            },
        }

    async def _create_landing_page(self, name: str, description: str) -> dict[str, Any]:
        """Generates a professional landing page using the WebsiteEngine."""
        from apps.core.tools.website_engine import WebsiteEngine

        engine = WebsiteEngine()

        # Recommended sections for a high-end landing page
        sections = ["hero", "features", "pricing", "testimonials", "faq", "cta", "footer"]

        # Generate the website
        result = await engine.generate_website(
            name=name, description=description, sections=sections, template="landing"
        )

        if result.get("success"):
            # In a real implementation, this would be uploaded to Shopify via API (Assets API)
            # For now, we save the HTML and report it
            html_path = f"/home/ubuntu/aria-ai/public/{result['filename']}"
            import os

            os.makedirs(os.path.dirname(html_path), exist_ok=True)
            with open(html_path, "w") as f:
                f.write(result["html"])

            return {
                "success": True,
                "html_path": html_path,
                "filename": result["filename"],
                "message": f"Landing page '{name}' generated successfully. Ready to upload to Shopify.",
            }

        return {"success": False, "error": "Could not generate the landing page."}
