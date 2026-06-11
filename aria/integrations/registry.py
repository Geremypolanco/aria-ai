"""Aria Integrations Registry.

Centralised registry that exposes every connected Zapier app as a
LangChain tool that AriaAgent can invoke autonomously.

Connected apps (38):
  CRM          : HubSpot
  E-commerce   : Shopify, Gumroad
  Productivity : Notion, Airtable, Trello, Asana, Google Workspace
                 (Docs, Sheets, Drive, Calendar, Tasks, Forms)
  Communication: Gmail, Telegram, Mailchimp
  Finance      : Stripe, PayPal
  Marketing    : Google Ads, Facebook Pages, Facebook Messenger,
                 Facebook Lead Ads, Facebook Conversions,
                 Facebook Custom Audiences, TikTok Lead Gen,
                 TikTok Conversions, LinkedIn, Buffer
  Analytics    : Google Analytics 4, Google Business Profile
  Forms        : Typeform, Jotform, Google Forms
  Code         : GitHub
  Storage      : Dropbox, Google Drive
  Scheduling   : Calendly, Google Calendar
  Audio        : ElevenLabs
  AI           : Hugging Face
  Utility      : API by Zapier
"""
from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
from langchain.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ZAPIER_NLA_BASE = "https://nla.zapier.com/api/v1/dynamic/exposed"


# ---------------------------------------------------------------------------
# Zapier NLA helper
# ---------------------------------------------------------------------------

async def _call_zapier_action(action_id: str, instructions: str) -> str:
    api_key = os.environ.get("ZAPIER_NLA_API_KEY", "")
    if not api_key:
        return "[ZAPIER_NLA_API_KEY not configured]"
    url = f"{ZAPIER_NLA_BASE}/{action_id}/execute/"
    payload = {"instructions": instructions, "preview_only": False}
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            return data.get("result", str(data))


def _make_zapier_tool(name: str, description: str, action_env_var: str) -> StructuredTool:
    class InputSchema(BaseModel):
        instructions: str = Field(..., description="Natural language instructions")

    import asyncio
    import concurrent.futures

    def _run(instructions: str) -> str:
        action_id = os.environ.get(action_env_var, "")
        if not action_id:
            return f"[{action_env_var} not set — configure it in .env or Fly secrets]"
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _call_zapier_action(action_id, instructions))
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(_call_zapier_action(action_id, instructions))
        except Exception as exc:
            logger.exception("Tool %s failed: %s", name, exc)
            return f"[Error: {exc}]"

    return StructuredTool(
        name=name,
        description=description,
        args_schema=InputSchema,
        func=_run,
    )


TOOL_DEFINITIONS: list[dict[str, str]] = [
    {"name": "hubspot_create_contact", "description": "Create or update a HubSpot CRM contact.", "env": "ZAPIER_HUBSPOT_CREATE_CONTACT"},
    {"name": "hubspot_find_contact", "description": "Search HubSpot CRM contacts by email or name.", "env": "ZAPIER_HUBSPOT_FIND_CONTACT"},
    {"name": "hubspot_create_deal", "description": "Create a HubSpot CRM deal/opportunity.", "env": "ZAPIER_HUBSPOT_CREATE_DEAL"},
    {"name": "hubspot_log_activity", "description": "Log a note or activity to a HubSpot contact.", "env": "ZAPIER_HUBSPOT_LOG_ACTIVITY"},
    {"name": "shopify_get_order", "description": "Retrieve a Shopify order by ID or status.", "env": "ZAPIER_SHOPIFY_GET_ORDER"},
    {"name": "shopify_create_product", "description": "Create a Shopify product with title, price, description.", "env": "ZAPIER_SHOPIFY_CREATE_PRODUCT"},
    {"name": "shopify_update_inventory", "description": "Update inventory for a Shopify product variant.", "env": "ZAPIER_SHOPIFY_UPDATE_INVENTORY"},
    {"name": "gumroad_create_product", "description": "Create a digital product on Gumroad.", "env": "ZAPIER_GUMROAD_CREATE_PRODUCT"},
    {"name": "notion_create_page", "description": "Create a Notion page in a database.", "env": "ZAPIER_NOTION_CREATE_PAGE"},
    {"name": "notion_search", "description": "Search Notion pages and databases.", "env": "ZAPIER_NOTION_SEARCH"},
    {"name": "airtable_create_record", "description": "Create a record in Airtable.", "env": "ZAPIER_AIRTABLE_CREATE_RECORD"},
    {"name": "airtable_find_record", "description": "Search for records in Airtable.", "env": "ZAPIER_AIRTABLE_FIND_RECORD"},
    {"name": "trello_create_card", "description": "Create a Trello card on a board/list.", "env": "ZAPIER_TRELLO_CREATE_CARD"},
    {"name": "trello_update_card", "description": "Update a Trello card — move, label, edit.", "env": "ZAPIER_TRELLO_UPDATE_CARD"},
    {"name": "asana_create_task", "description": "Create an Asana task with project and due date.", "env": "ZAPIER_ASANA_CREATE_TASK"},
    {"name": "asana_find_task", "description": "Search Asana tasks by name or project.", "env": "ZAPIER_ASANA_FIND_TASK"},
    {"name": "gmail_send_email", "description": "Send an email via Gmail.", "env": "ZAPIER_GMAIL_SEND"},
    {"name": "gmail_find_email", "description": "Search Gmail inbox for emails.", "env": "ZAPIER_GMAIL_FIND"},
    {"name": "google_calendar_create_event", "description": "Create a Google Calendar event.", "env": "ZAPIER_GCAL_CREATE_EVENT"},
    {"name": "google_calendar_find_event", "description": "Find upcoming Google Calendar events.", "env": "ZAPIER_GCAL_FIND_EVENT"},
    {"name": "google_sheets_append_row", "description": "Append a row to Google Sheets.", "env": "ZAPIER_GSHEETS_APPEND"},
    {"name": "google_sheets_lookup_row", "description": "Look up rows in Google Sheets.", "env": "ZAPIER_GSHEETS_LOOKUP"},
    {"name": "google_docs_create", "description": "Create a Google Doc with content.", "env": "ZAPIER_GDOCS_CREATE"},
    {"name": "google_drive_upload", "description": "Upload or create a file in Google Drive.", "env": "ZAPIER_GDRIVE_UPLOAD"},
    {"name": "google_tasks_create", "description": "Create a Google Task.", "env": "ZAPIER_GTASKS_CREATE"},
    {"name": "telegram_send_message", "description": "Send a Telegram message to a chat_id or channel.", "env": "ZAPIER_TELEGRAM_SEND"},
    {"name": "mailchimp_add_subscriber", "description": "Add/update a Mailchimp subscriber.", "env": "ZAPIER_MAILCHIMP_ADD_SUBSCRIBER"},
    {"name": "mailchimp_send_campaign", "description": "Create and send a Mailchimp campaign.", "env": "ZAPIER_MAILCHIMP_SEND_CAMPAIGN"},
    {"name": "stripe_create_payment_link", "description": "Create a Stripe payment link.", "env": "ZAPIER_STRIPE_PAYMENT_LINK"},
    {"name": "stripe_find_customer", "description": "Find a Stripe customer by email.", "env": "ZAPIER_STRIPE_FIND_CUSTOMER"},
    {"name": "paypal_create_invoice", "description": "Create and send a PayPal invoice.", "env": "ZAPIER_PAYPAL_CREATE_INVOICE"},
    {"name": "buffer_create_post", "description": "Schedule a social media post via Buffer.", "env": "ZAPIER_BUFFER_CREATE_POST"},
    {"name": "linkedin_share_post", "description": "Share a post on LinkedIn.", "env": "ZAPIER_LINKEDIN_SHARE"},
    {"name": "facebook_create_post", "description": "Create a post on a Facebook Page.", "env": "ZAPIER_FACEBOOK_CREATE_POST"},
    {"name": "google_ads_create_campaign", "description": "Create or update a Google Ads campaign.", "env": "ZAPIER_GOOGLE_ADS_CREATE"},
    {"name": "facebook_conversions_track", "description": "Send conversion events to Facebook Conversions API.", "env": "ZAPIER_FB_CONVERSIONS"},
    {"name": "google_analytics_get_report", "description": "Get a GA4 analytics report.", "env": "ZAPIER_GA4_REPORT"},
    {"name": "google_business_profile_update", "description": "Update Google Business Profile.", "env": "ZAPIER_GBP_UPDATE"},
    {"name": "typeform_get_responses", "description": "Get Typeform form responses.", "env": "ZAPIER_TYPEFORM_RESPONSES"},
    {"name": "jotform_get_submissions", "description": "Get Jotform submissions.", "env": "ZAPIER_JOTFORM_SUBMISSIONS"},
    {"name": "calendly_get_events", "description": "Get upcoming Calendly scheduled events.", "env": "ZAPIER_CALENDLY_EVENTS"},
    {"name": "calendly_create_invite", "description": "Create a Calendly one-off invite.", "env": "ZAPIER_CALENDLY_INVITE"},
    {"name": "github_create_issue", "description": "Create a GitHub issue.", "env": "ZAPIER_GITHUB_CREATE_ISSUE"},
    {"name": "github_create_file", "description": "Create or update a file in GitHub.", "env": "ZAPIER_GITHUB_CREATE_FILE"},
    {"name": "github_get_file", "description": "Read a file from GitHub.", "env": "ZAPIER_GITHUB_GET_FILE"},
    {"name": "dropbox_upload_file", "description": "Upload a file to Dropbox.", "env": "ZAPIER_DROPBOX_UPLOAD"},
    {"name": "elevenlabs_text_to_speech", "description": "Convert text to speech via ElevenLabs.", "env": "ZAPIER_ELEVENLABS_TTS"},
    {"name": "huggingface_run_model", "description": "Run inference on a Hugging Face model.", "env": "ZAPIER_HUGGINGFACE_INFER"},
]

_tools_cache: list[StructuredTool] | None = None


def get_all_tools() -> list[StructuredTool]:
    global _tools_cache
    if _tools_cache is None:
        _tools_cache = [
            _make_zapier_tool(t["name"], t["description"], t["env"])
            for t in TOOL_DEFINITIONS
        ]
        logger.info("Loaded %d Aria integration tools.", len(_tools_cache))
    return _tools_cache


def get_tool_names() -> list[str]:
    return [t["name"] for t in TOOL_DEFINITIONS]
