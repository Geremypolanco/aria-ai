"""
ARIA Publishing Tools — Automatic publishing on content platforms.

Supported platforms:
- Medium (official API)
- Dev.to (official API)
- Hashnode (GraphQL API)
- Substack (via email/web)

All of them have a free tier and are activated with a simple API key.
"""

from __future__ import annotations

import logging
import re

import httpx

from apps.core.config import settings

logger = logging.getLogger("aria.publishing")


class PublishingTools:

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    # ── MEDIUM ────────────────────────────────────────────

    async def publish_medium(self, article: dict) -> dict:
        """
        Publishes to Medium using the Integration Token.
        Requires: MEDIUM_TOKEN in secrets.
        To obtain it: medium.com/me/settings -> Integration tokens
        """
        if not settings.MEDIUM_TOKEN:
            return {"success": False, "skipped": True, "reason": "MEDIUM_TOKEN not configured"}

        try:
            # Get user ID
            me_res = await self._http.get(
                "https://api.medium.com/v1/me",
                headers={"Authorization": f"Bearer {settings.MEDIUM_TOKEN}"},
            )
            if me_res.status_code != 200:
                return {"success": False, "error": f"Medium auth error: {me_res.status_code}"}

            user_id = me_res.json()["data"]["id"]

            title = article.get("title", "Article")
            body_html = article.get("body_html", article.get("body", ""))
            tags = article.get("tags", [])[:5]

            post_res = await self._http.post(
                f"https://api.medium.com/v1/users/{user_id}/posts",
                headers={
                    "Authorization": f"Bearer {settings.MEDIUM_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "title": title,
                    "contentFormat": "html",
                    "content": body_html,
                    "tags": tags,
                    "publishStatus": "public",
                    "notifyFollowers": True,
                },
            )

            if post_res.status_code in (200, 201):
                data = post_res.json().get("data", {})
                url = data.get("url", "")
                logger.info("[Publishing] Medium: %s", url)
                return {"success": True, "platform": "medium", "url": url, "id": data.get("id")}
            return {"success": False, "error": post_res.text[:200]}

        except Exception as exc:
            logger.error("[Publishing] Medium error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── DEV.TO ────────────────────────────────────────────

    async def publish_devto(self, article: dict) -> dict:
        """
        Publishes to Dev.to.
        Requires: DEVTO_API_KEY in secrets.
        To obtain it: dev.to/settings/extensions -> DEV Community API Keys
        """
        if not settings.DEVTO_API_KEY:
            return {"success": False, "skipped": True, "reason": "DEVTO_API_KEY not configured"}

        try:
            title = article.get("title", "Article")
            body = article.get("body", "")
            tags = [
                t.lower().replace(" ", "").replace("-", "")[:20]
                for t in article.get("tags", [])[:4]
            ]
            meta = article.get("meta_description", "")

            res = await self._http.post(
                "https://dev.to/api/articles",
                headers={"api-key": settings.DEVTO_API_KEY, "Content-Type": "application/json"},
                json={
                    "article": {
                        "title": title,
                        "published": True,
                        "body_markdown": body,
                        "tags": tags,
                        "description": meta[:155],
                    }
                },
            )

            if res.status_code in (200, 201):
                data = res.json()
                url = data.get("url", f"https://dev.to/{data.get('id', '')}")
                logger.info("[Publishing] Dev.to: %s", url)
                return {"success": True, "platform": "devto", "url": url, "id": data.get("id")}
            return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            logger.error("[Publishing] Dev.to error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── HASHNODE ──────────────────────────────────────────

    async def publish_hashnode(self, article: dict) -> dict:
        """
        Publishes to Hashnode via GraphQL.
        Requires: HASHNODE_TOKEN and HASHNODE_PUBLICATION_ID in secrets.
        To get the token: hashnode.com/settings -> Developer -> Personal Access Token
        To get the publication ID: from your blog's dashboard
        """
        if not settings.HASHNODE_TOKEN or not settings.HASHNODE_PUBLICATION_ID:
            return {
                "success": False,
                "skipped": True,
                "reason": "HASHNODE_TOKEN or HASHNODE_PUBLICATION_ID not configured",
            }

        try:
            title = article.get("title", "Article")
            body = article.get("body", "")
            tags = [
                {"name": t, "slug": t.lower().replace(" ", "-")}
                for t in article.get("tags", [])[:5]
            ]
            meta = article.get("meta_description", "")

            mutation = """
            mutation PublishPost($input: PublishPostInput!) {
              publishPost(input: $input) {
                post {
                  id
                  url
                  title
                }
              }
            }
            """

            variables = {
                "input": {
                    "title": title,
                    "subtitle": meta[:255] if meta else None,
                    "publicationId": settings.HASHNODE_PUBLICATION_ID,
                    "contentMarkdown": body,
                    "tags": tags,
                    "metaTags": {
                        "title": title[:70],
                        "description": meta[:155],
                    },
                }
            }

            res = await self._http.post(
                "https://gql.hashnode.com",
                headers={
                    "Authorization": settings.HASHNODE_TOKEN,
                    "Content-Type": "application/json",
                },
                json={"query": mutation, "variables": variables},
            )

            if res.status_code == 200:
                data = res.json()
                if "errors" in data:
                    return {"success": False, "error": str(data["errors"])[:200]}
                post = data.get("data", {}).get("publishPost", {}).get("post", {})
                url = post.get("url", "")
                logger.info("[Publishing] Hashnode: %s", url)
                return {"success": True, "platform": "hashnode", "url": url, "id": post.get("id")}
            return {"success": False, "error": res.text[:200]}

        except Exception as exc:
            logger.error("[Publishing] Hashnode error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── EMAIL NEWSLETTER ──────────────────────────────────

    async def send_newsletter(
        self,
        subject: str,
        html_content: str,
        plain_text: str = "",
        to_override: str | None = None,
    ) -> dict:
        """
        Sends a newsletter using the best available provider.
        Order: Resend → SendGrid → Mailgun
        to_override: specific recipient (if the configured list is not used).
        """
        if not plain_text:
            plain_text = re.sub(r"<[^>]+>", "", html_content)

        providers = [
            ("resend", self._send_via_resend),
            ("sendgrid", self._send_via_sendgrid),
            ("mailgun", self._send_via_mailgun),
        ]
        for name, fn in providers:
            try:
                result = await fn(subject, html_content, plain_text, to=to_override)
                if result.get("success"):
                    logger.info("[Publishing] Newsletter sent via %s", name)
                    return {**result, "provider": name}
            except Exception as exc:
                logger.warning("[Publishing] %s newsletter error: %s", name, exc)
        return {"success": False, "error": "All email providers failed"}

    async def _send_via_resend(
        self, subject: str, html: str, text: str, to: str | None = None
    ) -> dict:
        """Resend: 3,000 emails/month free."""
        if not settings.RESEND_API_KEY:
            return {"success": False, "skipped": True}
        to_email = (
            to or settings.NEWSLETTER_LIST_EMAIL or getattr(settings, "OWNER_EMAIL", None) or ""
        )
        if not to_email:
            return {"success": False, "skipped": True}
        res = await self._http.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.EMAIL_FROM or "ARIA <newsletter@aria-ai.dev>",
                "to": [to_email],
                "subject": subject,
                "html": html,
                "text": text,
            },
        )
        if res.status_code in (200, 201):
            return {"success": True, "id": res.json().get("id")}
        return {"success": False, "error": res.text[:200]}

    async def _send_via_sendgrid(
        self, subject: str, html: str, text: str, to: str | None = None
    ) -> dict:
        """SendGrid: 100 emails/day free."""
        if not settings.SENDGRID_API_KEY:
            return {"success": False, "skipped": True}
        from_email = settings.EMAIL_FROM or "noreply@aria-ai.dev"
        to_email = (
            to or settings.NEWSLETTER_LIST_EMAIL or getattr(settings, "OWNER_EMAIL", None) or ""
        )
        if not to_email:
            return {"success": False, "skipped": True}
        res = await self._http.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_email},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": text},
                    {"type": "text/html", "value": html},
                ],
            },
        )
        if res.status_code == 202:
            return {"success": True}
        return {"success": False, "error": res.text[:200]}

    async def _send_via_mailgun(
        self, subject: str, html: str, text: str, to: str | None = None
    ) -> dict:
        """Mailgun: 5,000 emails/month free (3-month trial)."""
        if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
            return {"success": False, "skipped": True}
        to_email = (
            to or settings.NEWSLETTER_LIST_EMAIL or getattr(settings, "OWNER_EMAIL", None) or ""
        )
        if not to_email:
            return {"success": False, "skipped": True}
        res = await self._http.post(
            f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data={
                "from": settings.EMAIL_FROM or f"ARIA <noreply@{settings.MAILGUN_DOMAIN}>",
                "to": [to_email],
                "subject": subject,
                "text": text,
                "html": html,
            },
        )
        if res.status_code == 200:
            return {"success": True, "id": res.json().get("id")}
        return {"success": False, "error": res.text[:200]}
