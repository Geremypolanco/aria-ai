"""
Product page optimizer and rewriter.
Rewrites Shopify product descriptions for maximum SEO and conversion performance.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

logger = logging.getLogger("aria.content.product_pages")

_CACHE_KEY = "content:product_pages:v1"
_CACHE_TTL = 86400 * 60  # 60 days

# Conversion elements to detect in product descriptions
_CONVERSION_ELEMENTS = [
    "guarantee",
    "free shipping",
    "limited",
    "exclusive",
    "sale",
    "discount",
    "reviews",
    "rated",
    "stars",
    "trusted",
    "proven",
    "award",
    "best seller",
    "popular",
    "new",
    "in stock",
    "bundle",
    "save",
    "bonus",
    "fast",
    "premium",
    "quality",
]

_BENEFIT_WORDS = ["benefit", "improve", "boost", "increase", "reduce", "save", "transform", "achieve"]
_SOCIAL_PROOF_WORDS = ["reviews", "customers", "rated", "stars", "trusted", "popular", "best seller"]
_URGENCY_WORDS = ["limited", "last chance", "only", "hurry", "exclusive", "today only", "ending soon"]
_PRICE_ANCHORING_WORDS = ["was", "save", "off", "discount", "% off", "deal", "compare at"]


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class ProductPageAnalysis:
    product_id: str
    title: str
    original_description: str
    optimized_title: str
    optimized_description: str
    seo_score_before: float
    seo_score_after: float
    conversion_elements: list[str]
    cta_recommendation: str
    keywords_added: list[str]

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "title": self.title,
            "original_description": self.original_description,
            "optimized_title": self.optimized_title,
            "optimized_description": self.optimized_description,
            "seo_score_before": self.seo_score_before,
            "seo_score_after": self.seo_score_after,
            "conversion_elements": self.conversion_elements,
            "cta_recommendation": self.cta_recommendation,
            "keywords_added": self.keywords_added,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _score_description(description: str) -> tuple[float, list[str]]:
    """Score a product description by counting conversion elements present."""
    desc_lower = description.lower()
    words = desc_lower.split()
    word_count = len(words)
    found_elements: list[str] = []
    score = 0.0

    # Word count
    if word_count >= 150:
        score += 0.2
        found_elements.append("sufficient_length")
    elif word_count >= 75:
        score += 0.1

    # Benefit statements
    if any(w in desc_lower for w in _BENEFIT_WORDS):
        score += 0.2
        found_elements.append("benefit_statements")

    # Social proof
    if any(w in desc_lower for w in _SOCIAL_PROOF_WORDS):
        score += 0.2
        found_elements.append("social_proof")

    # Urgency/scarcity
    if any(w in desc_lower for w in _URGENCY_WORDS):
        score += 0.2
        found_elements.append("urgency_scarcity")

    # Price anchoring
    if any(w in desc_lower for w in _PRICE_ANCHORING_WORDS):
        score += 0.1
        found_elements.append("price_anchoring")

    # CTA presence
    cta_words = ["buy now", "order now", "add to cart", "shop now", "get yours", "purchase"]
    if any(w in desc_lower for w in cta_words):
        score += 0.1
        found_elements.append("clear_cta")

    return round(min(1.0, score), 2), found_elements


def _default_cta(category: str) -> str:
    mapping = {
        "electronics": "Add to cart now — fast shipping guaranteed.",
        "clothing": "Shop your size today — limited stock available.",
        "beauty": "Try it risk-free with our 30-day money-back guarantee.",
        "food": "Order now and taste the difference — free shipping on orders over $35.",
        "fitness": "Start your transformation — add to cart and get free shipping today.",
    }
    cat_lower = category.lower()
    for key, cta in mapping.items():
        if key in cat_lower:
            return cta
    return "Add to cart today — satisfaction guaranteed or your money back."


# ── Main class ─────────────────────────────────────────────────────────────────

class ProductWriter:
    """Product page optimizer and rewriter for Shopify and e-commerce stores."""

    def __init__(self) -> None:
        self._ai = get_ai_client()
        self._analyses: list[dict] = []
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, list):
                self._analyses = data
        except Exception as exc:
            logger.warning("ProductWriter._load failed: %s", exc)
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._analyses, ttl_seconds=_CACHE_TTL)
        except Exception as exc:
            logger.warning("ProductWriter._save failed: %s", exc)

    async def optimize_product(
        self,
        product_id: str,
        title: str,
        description: str,
        category: str = "",
    ) -> ProductPageAnalysis:
        """Rewrite product description for maximum conversion and SEO."""
        await self._load()

        # Score before
        score_before, elements_before = _score_description(description)

        # Optimized title: include category keyword if provided
        optimized_title = f"{title} — Best {category} {title}" if category else title
        optimized_title = optimized_title[:100]

        # AI rewrite
        optimized_description = ""
        keywords_added: list[str] = []
        try:
            resp = await self._ai.complete(
                system="You are a world-class e-commerce copywriter specializing in high-converting product pages.",
                user=(
                    f"Rewrite this Shopify product description to maximize conversion.\n\n"
                    f"Include:\n"
                    f"(1) hook opening with primary benefit\n"
                    f"(2) 3 bullet points of key benefits\n"
                    f"(3) who it's for\n"
                    f"(4) social proof element\n"
                    f"(5) urgency/scarcity\n\n"
                    f"Under 200 words. Product: {title}. Category: {category}.\n"
                    f"Original: {description[:300]}"
                ),
                model=AIModel.CREATIVE,
                max_tokens=400,
                agent_name="product_writer",
            )
            if resp.success and resp.content:
                optimized_description = resp.content
                # Detect what keywords were added
                orig_lower = description.lower()
                opt_lower = optimized_description.lower()
                for elem_word in _CONVERSION_ELEMENTS:
                    if elem_word in opt_lower and elem_word not in orig_lower:
                        keywords_added.append(elem_word)
        except Exception as exc:
            logger.warning("ProductWriter.optimize_product AI failed: %s", exc)

        if not optimized_description:
            # Fallback: structured template
            optimized_description = (
                f"**{title}** — The solution you've been looking for.\n\n"
                f"**Key Benefits:**\n"
                f"- Premium quality you can trust\n"
                f"- Designed for maximum performance\n"
                f"- Built to last with superior materials\n\n"
                f"**Perfect for:** Anyone who wants the best {category or 'product'} experience.\n\n"
                f"Trusted by thousands of satisfied customers. ⭐⭐⭐⭐⭐\n\n"
                f"**Limited stock available** — Order now and get free shipping!"
            )
            keywords_added = ["premium", "trusted", "limited", "free shipping"]

        # Score after
        score_after, elements_after = _score_description(optimized_description)
        cta = _default_cta(category)

        analysis = ProductPageAnalysis(
            product_id=product_id,
            title=title,
            original_description=description,
            optimized_title=optimized_title,
            optimized_description=optimized_description,
            seo_score_before=score_before,
            seo_score_after=score_after,
            conversion_elements=elements_after,
            cta_recommendation=cta,
            keywords_added=keywords_added,
        )
        self._analyses.append(analysis.to_dict())
        await self._save()
        return analysis

    async def batch_optimize(self, products: list[dict]) -> list[ProductPageAnalysis]:
        """Optimize multiple products."""
        results = []
        for product in products:
            analysis = await self.optimize_product(
                product_id=product.get("product_id", str(uuid.uuid4())),
                title=product.get("title", ""),
                description=product.get("description", ""),
                category=product.get("category", ""),
            )
            results.append(analysis)
        return results

    async def generate_product_faq(
        self,
        product_id: str,
        title: str,
        category: str,
    ) -> list[dict]:
        """AI-generate 5 FAQ items for a product page."""
        try:
            resp = await self._ai.complete(
                system="You are an e-commerce specialist writing product FAQ sections.",
                user=(
                    f"Generate 5 FAQ questions and answers for this product:\n"
                    f"Product: {title}\nCategory: {category}\n\n"
                    "Format EXACTLY as:\n"
                    "Q1: <question>\n"
                    "A1: <answer>\n"
                    "Q2: <question>\n"
                    "A2: <answer>\n"
                    "(and so on through Q5/A5)"
                ),
                model=AIModel.FAST,
                max_tokens=500,
                agent_name="product_writer",
            )
            if resp.success and resp.content:
                lines = resp.content.strip().split("\n")
                faqs = []
                current_q = None
                for line in lines:
                    line = line.strip()
                    if line.startswith("Q") and ":" in line:
                        current_q = line.split(":", 1)[1].strip()
                    elif line.startswith("A") and ":" in line and current_q:
                        answer = line.split(":", 1)[1].strip()
                        faqs.append({"question": current_q, "answer": answer})
                        current_q = None
                if len(faqs) >= 3:
                    return faqs[:5]
        except Exception as exc:
            logger.warning("ProductWriter.generate_product_faq failed: %s", exc)

        # Fallback FAQ
        return [
            {"question": f"What is {title}?", "answer": f"{title} is a premium {category} product designed for maximum performance."},
            {"question": "What is the return policy?", "answer": "We offer a 30-day money-back guarantee on all products."},
            {"question": "How fast is shipping?", "answer": "Standard shipping takes 3-5 business days. Express options available."},
            {"question": f"Is {title} right for me?", "answer": f"{title} is perfect for anyone looking for quality {category} solutions."},
            {"question": "Do you offer bulk discounts?", "answer": "Yes! Contact us for bulk pricing on orders of 10+ units."},
        ]

    async def create_collection_description(
        self,
        collection_name: str,
        products: list[str],
    ) -> str:
        """AI-generate a collection page description."""
        try:
            product_list = ", ".join(products[:5])
            resp = await self._ai.complete(
                system="You are an expert e-commerce copywriter.",
                user=(
                    f"Write a compelling collection page description for '{collection_name}'.\n"
                    f"Featured products: {product_list}\n\n"
                    "Requirements:\n"
                    "- 100-150 words\n"
                    "- Include SEO keywords naturally\n"
                    "- Highlight the collection's unique value\n"
                    "- End with a call to action"
                ),
                model=AIModel.CREATIVE,
                max_tokens=250,
                agent_name="product_writer",
            )
            if resp.success and resp.content:
                return resp.content
        except Exception as exc:
            logger.warning("ProductWriter.create_collection_description failed: %s", exc)

        return (
            f"Discover our premium {collection_name} collection — carefully curated for quality, "
            f"performance, and style. Whether you're a beginner or a pro, you'll find exactly what "
            f"you need in our selection of {', '.join(products[:3])} and more. "
            f"Shop with confidence with our 30-day return policy and free shipping on orders over $50. "
            f"Browse the full collection today."
        )

    def optimization_history(self) -> list[dict]:
        return list(self._analyses)

    def stats(self) -> dict:
        if not self._analyses:
            return {"total_optimized": 0, "avg_seo_improvement": 0.0}
        total = len(self._analyses)
        improvements = [
            a.get("seo_score_after", 0) - a.get("seo_score_before", 0)
            for a in self._analyses
        ]
        avg_improvement = round(sum(improvements) / total, 3)
        return {
            "total_optimized": total,
            "avg_seo_improvement": avg_improvement,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_product_writer: Optional[ProductWriter] = None


def get_product_writer() -> ProductWriter:
    global _product_writer
    if _product_writer is None:
        _product_writer = ProductWriter()
    return _product_writer
