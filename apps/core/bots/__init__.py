"""
bots/ — Bots especializados de ARIA.

Cada bot maneja un dominio específico de forma autónoma,
liberando a Aria de tareas repetitivas y pesadas.
"""
from apps.core.bots.content_bot import ContentBot
from apps.core.bots.research_bot import ResearchBot
from apps.core.bots.opportunity_bot import OpportunityBot
from apps.core.bots.finance_bot import FinanceBot
from apps.core.bots.monitor_bot import MonitorBot
from apps.core.bots.shopify_bot import ShopifyBot
from apps.core.bots.email_bot import EmailBot
from apps.core.bots.social_bot import SocialBot
from apps.core.bots.scheduler_bot import SchedulerBot
from apps.core.bots.digest_bot import DigestBot

__all__ = [
    "ContentBot", "ResearchBot", "OpportunityBot", "FinanceBot",
    "MonitorBot", "ShopifyBot", "EmailBot", "SocialBot",
    "SchedulerBot", "DigestBot",
]
