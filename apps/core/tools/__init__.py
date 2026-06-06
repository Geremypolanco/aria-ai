"""
tools/__init__.py -- Todas las herramientas de ARIA AI.
"""
from apps.core.tools.ai_client import AIModel, AIProvider, AIResponse, get_ai_client
from apps.core.tools.commerce_tools import CommerceTools
from apps.core.tools.content_tools import ContentTools
from apps.core.tools.market_tools import MarketTools
from apps.core.tools.buffer_tools import BufferTools
from apps.core.tools.mailchimp_tools import MailchimpTools
from apps.core.tools.google_tools import GoogleTools
from apps.core.tools.google_suite import GoogleSuite
from apps.core.tools.huggingface_suite import HuggingFaceSuite
from apps.core.tools.self_improvement import SelfImprovementEngine
from apps.core.tools.api_discovery import APIDiscovery, KNOWN_FREE_APIS

APIDiscoveryEngine = APIDiscovery

from apps.core.tools.canva_tools import CanvaTools
from apps.core.tools.airtable_tools import AirtableTools
from apps.core.tools.telegram_bot import AriaTelegramBot, get_bot
from apps.core.tools.social_media import SocialMediaManager
from apps.core.tools.content_pipeline import ContentPipeline
from apps.core.tools.publishing_tools import PublishingTools
from apps.core.tools.social_content_tools import SocialContentTools
from apps.core.tools.affiliate_tools import AffiliateTools
from apps.core.tools.cloudinary_tools import CloudinaryTools
from apps.core.tools.chloe_tools import ChloeTools

from apps.core.tools.sales_intelligence import (
    SalesIntelligence, SPINSelling, ChallengerSale, AIDACopywriter, PASCopywriter,
    StoryBrandFramework, ValuePropositionCanvas, SalesObjectionHandler,
    ClosingTechniques, NicheTargetingEngine, DigitalProductFormulas,
    POWER_WORDS, EMAIL_SUBJECT_FORMULAS, HEADLINE_FORMULAS,
)
from apps.core.tools.copywriting_engine import (
    CopywritingEngine, SalesPageWriter, SocialMediaCopywriter,
    AdCopywriter, ProductDescriptionWriter, HOOKS_BY_FORMAT, EMAIL_SEQUENCES,
)
from apps.core.tools.followup_engine import (
    FollowUpEngine, LeadScorer, FOLLOWUP_TIMING, FOLLOWUP_TEMPLATES,
)
from apps.core.tools.revenue_engine import (
    RevenueEngine, get_revenue_engine, READY_TO_LAUNCH_PRODUCTS,
)
from apps.core.tools.audience_profiler import AudienceProfiler, BUYER_PERSONAS

__all__ = [
    "AIModel", "AIProvider", "AIResponse", "get_ai_client",
    "CommerceTools", "ContentTools", "MarketTools",
    "BufferTools", "MailchimpTools", "GoogleTools", "GoogleSuite",
    "HuggingFaceSuite", "SelfImprovementEngine",
    "APIDiscovery", "APIDiscoveryEngine", "KNOWN_FREE_APIS",
    "CanvaTools", "AirtableTools", "AriaTelegramBot", "get_bot",
    "SocialMediaManager", "ContentPipeline", "PublishingTools",
    "SocialContentTools", "AffiliateTools", "CloudinaryTools", "ChloeTools",
    "SalesIntelligence", "SPINSelling", "ChallengerSale", "AIDACopywriter", "PASCopywriter",
    "StoryBrandFramework", "ValuePropositionCanvas", "SalesObjectionHandler",
    "ClosingTechniques", "NicheTargetingEngine", "DigitalProductFormulas",
    "POWER_WORDS", "EMAIL_SUBJECT_FORMULAS", "HEADLINE_FORMULAS",
    "CopywritingEngine", "SalesPageWriter", "SocialMediaCopywriter",
    "AdCopywriter", "ProductDescriptionWriter", "HOOKS_BY_FORMAT", "EMAIL_SEQUENCES",
    "FollowUpEngine", "LeadScorer", "FOLLOWUP_TIMING", "FOLLOWUP_TEMPLATES",
    "RevenueEngine", "get_revenue_engine", "READY_TO_LAUNCH_PRODUCTS",
    "AudienceProfiler", "BUYER_PERSONAS",
]
