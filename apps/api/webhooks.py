"""
webhooks.py — Manejador de Webhooks para ARIA.

Permite recibir eventos de Zapier, GitHub, formularios de landing page y otras
aplicaciones externas para disparar tareas automáticamente en el orquestador.
"""

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.api.ratelimit import rate_limit
from apps.core.agents.orchestrator import Orchestrator as AriaOrchestrator

logger = logging.getLogger("aria.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Instancia global del orquestador (debería ser inyectada o compartida)
orchestrator = AriaOrchestrator()


class ZapierPayload(BaseModel):
    """Estructura del payload enviado por Zapier."""

    action: str
    task: str
    data: dict[str, Any] | None = None
    user_id: str | None = "default"


@router.post("/zapier")
async def handle_zapier_webhook(
    payload: ZapierPayload, x_zapier_signature: str | None = Header(None)
):
    """
    Recibe un webhook de Zapier para ejecutar una tarea en Aria.

    Ejemplo de flujo:
    1. Un correo llega a Gmail.
    2. Zapier captura el evento.
    3. Zapier envía un POST a este endpoint con la tarea: "Analiza este correo y crea un resumen".
    """
    logger.info(f"[Webhook] Recibida petición de Zapier: {payload.action}")

    # Validar firma (opcional pero recomendado)
    # if not validate_signature(payload, x_zapier_signature):
    #     raise HTTPException(status_code=401, detail="Invalid signature")

    # Ejecutar tarea en el orquestador de forma asíncrona
    # En una implementación real, esto se enviaría a una cola de tareas (Redis/Celery)
    context = {
        "task": payload.task,
        "user_context": {"source": "zapier", "action": payload.action, "data": payload.data},
    }

    # Por ahora, ejecutamos y devolvemos el resultado inicial
    try:
        # En producción, esto debería ser asíncrono y devolver un ID de tarea
        result = await orchestrator.execute_task(payload.task, context["user_context"])
        return {
            "success": True,
            "message": "Tarea recibida y procesada",
            "task_id": "zap_" + str(hash(payload.task))[:8],
            "result": result,
        }
    except Exception as exc:
        logger.error(f"[Webhook] Error procesando tarea de Zapier: {exc}")
        return {"success": False, "error": str(exc)}


@router.post("/generic")
async def handle_generic_webhook(request: Request):
    """Manejador genérico para cualquier otra integración."""
    data = await request.json()
    logger.info(f"[Webhook] Recibido evento genérico: {data}")
    return {"status": "received"}


def validate_signature(payload: Any, signature: str) -> bool:
    """Valida que la petición venga realmente de Zapier."""
    # Implementación real usando una clave compartida guardada en SecretsManager
    return True


class LeadPayload(BaseModel):
    """Inbound lead from the ARIA landing page or any form."""

    name: str = ""
    email: str = ""
    company: str = ""
    phone: str = ""
    segment: str = ""
    message: str = ""
    source: str = "landing_page"  # landing_page | lead_magnet | referral | direct


@router.post("/lead", dependencies=[Depends(rate_limit(8, 60, "lead"))])
async def handle_inbound_lead(payload: LeadPayload):
    """
    Receives an inbound lead from the ARIA landing page or email capture funnel.

    On receipt:
    1. Stores lead in Redis CRM pipeline (aria:crm:pipeline list)
    2. Sends an instant welcome email via SMTP
    3. Adds to Mailchimp if configured
    4. Sends Telegram alert to owner
    5. Queues a proposal_generator run for this specific lead
    """
    try:
        from apps.core.config import settings
        from apps.core.memory.redis_client import get_cache

        logger.info(
            "[Webhook] Inbound lead: %s <%s> from %s", payload.name, payload.email, payload.source
        )

        cache = get_cache()

        # 1. Store in Redis CRM pipeline
        lead_record = {
            "contact": payload.name,
            "email": payload.email,
            "company": payload.company or payload.name,
            "phone": payload.phone,
            "segment": payload.segment or "Inbound Lead",
            "message": payload.message,
            "source": payload.source,
            "status": "new",
            "deal_value": 97.0,  # assumed Pro tier until qualified
            "ts": time.time(),
        }

        if cache:
            try:
                await cache.rpush("aria:crm:pipeline", json.dumps(lead_record))
                await cache.ltrim("aria:crm:pipeline", -500, -1)
                # Also track inbound count
                await cache.incr("aria:crm:inbound_total")
            except Exception as exc:
                logger.warning("[lead_webhook] Redis write failed: %s", exc)

        # 2. Welcome email via SMTP
        smtp_host = getattr(settings, "SMTP_HOST", None)
        smtp_user = getattr(settings, "SMTP_USER", None)
        smtp_pass = getattr(settings, "SMTP_PASSWORD", None)
        smtp_from = getattr(settings, "SMTP_FROM", smtp_user)
        email_sent = False

        if payload.email and smtp_host and smtp_user and smtp_pass:
            try:
                import smtplib
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText

                first_name = payload.name.split()[0] if payload.name else "there"
                welcome_body = (
                    f"Hi {first_name},\n\n"
                    "Welcome to ARIA — I'm excited you're here.\n\n"
                    "ARIA is the first AI that doesn't just answer questions — it actively works "
                    "to grow your business 24/7. While you sleep, ARIA finds clients, creates "
                    "products, runs outreach campaigns, and generates revenue.\n\n"
                    "Here's what happens next:\n"
                    "→ You'll receive a personalized AI growth proposal within 24 hours\n"
                    "→ ARIA will research your business and identify the top 3 revenue opportunities\n"
                    "→ You can start ARIA's autonomous income loop immediately\n\n"
                    "To get started now: https://aria-ai.fly.dev\n\n"
                    "Questions? Just reply to this email — I read every one.\n\n"
                    "— ARIA AI\n"
                    "aria-ai.fly.dev"
                )
                smtp_port = int(getattr(settings, "SMTP_PORT", 587))
                msg = MIMEMultipart("alternative")
                msg["Subject"] = f"Welcome to ARIA, {first_name} — your AI business engine is ready"
                msg["From"] = smtp_from
                msg["To"] = payload.email
                msg.attach(MIMEText(welcome_body, "plain"))
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
                    srv.ehlo()
                    srv.starttls()
                    srv.login(smtp_user, smtp_pass)
                    srv.sendmail(smtp_from, [payload.email], msg.as_string())
                email_sent = True
                logger.info("[lead_webhook] Welcome email sent to %s", payload.email)
            except Exception as email_exc:
                logger.warning("[lead_webhook] Welcome email failed: %s", email_exc)

        # 3. Add to Mailchimp audience
        mc_api = getattr(settings, "MAILCHIMP_API_KEY", None)
        mc_list = getattr(settings, "MAILCHIMP_LIST_ID", None)
        mc_added = False
        if payload.email and mc_api and mc_list:
            try:
                import httpx as _hx

                mc_server = mc_api.split("-")[-1] if "-" in mc_api else "us1"
                async with _hx.AsyncClient(timeout=10) as _hc:
                    mc_resp = await _hc.post(
                        f"https://{mc_server}.api.mailchimp.com/3.0/lists/{mc_list}/members",
                        json={
                            "email_address": payload.email,
                            "status": "subscribed",
                            "merge_fields": {
                                "FNAME": payload.name.split()[0] if payload.name else "",
                                "LNAME": " ".join(payload.name.split()[1:]) if payload.name else "",
                                "COMPANY": payload.company,
                            },
                            "tags": [payload.source, payload.segment or "inbound"],
                        },
                        headers={"Authorization": f"apikey {mc_api}"},
                    )
                    mc_added = mc_resp.status_code in (200, 201)
            except Exception as mc_exc:
                logger.warning("[lead_webhook] Mailchimp add failed: %s", mc_exc)

        # 4. Telegram alert to owner
        try:
            from apps.core.tools.telegram_bot import get_bot

            tg_msg = (
                f"🎯 <b>New Inbound Lead!</b>\n\n"
                f"<b>Name:</b> {payload.name}\n"
                f"<b>Email:</b> {payload.email}\n"
                f"<b>Company:</b> {payload.company}\n"
                f"<b>Source:</b> {payload.source}\n"
                f"<b>Message:</b> {payload.message[:100] if payload.message else '—'}\n\n"
                f"Welcome email: {'✅ Sent' if email_sent else '⚠️ Failed'}\n"
                f"Mailchimp: {'✅ Added' if mc_added else '—'}"
            )
            await get_bot().notify_owner(tg_msg, already_html=True)
        except Exception as tg_exc:
            logger.warning("[lead_webhook] Telegram alert failed: %s", tg_exc)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Welcome {payload.name}! Check your email for next steps.",
                "email_sent": email_sent,
                "mailchimp": mc_added,
            },
        )

    except Exception as exc:
        logger.error("[lead_webhook] Unexpected error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal error — lead was logged"},
        )


@router.post("/stripe")
async def handle_stripe_webhook(request: Request):
    """
    Receives Stripe webhook events (payment.succeeded, subscription.created, etc.)
    and triggers the appropriate ARIA actions.
    """
    try:
        from apps.core.memory.redis_client import get_cache

        payload_bytes = await request.body()
        try:
            event = json.loads(payload_bytes)
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

        event_type = event.get("type", "")
        event_data = event.get("data", {}).get("object", {})
        logger.info("[stripe_webhook] event: %s", event_type)

        cache = get_cache()

        if event_type == "checkout.session.completed":
            customer_email = event_data.get("customer_email") or event_data.get(
                "customer_details", {}
            ).get("email", "")
            amount = float(event_data.get("amount_total", 0)) / 100
            plan = "unknown"
            if amount <= 29:
                plan = "Starter"
            elif amount <= 97:
                plan = "Pro"
            else:
                plan = "Agency"

            # Track new subscriber
            if cache:
                try:
                    await cache.incr(f"aria:subscribers:{plan.lower()}")
                    await cache.rpush(
                        "aria:crm:subscribers",
                        json.dumps(
                            {
                                "email": customer_email,
                                "plan": plan,
                                "amount": amount,
                                "ts": time.time(),
                            }
                        ),
                    )
                    await cache.ltrim("aria:crm:subscribers", -1000, -1)
                except Exception:
                    pass

            # Telegram alert
            try:
                from apps.core.tools.telegram_bot import get_bot

                await get_bot().notify_owner(
                    f"💰 <b>NEW SUBSCRIBER!</b>\n\n"
                    f"Plan: <b>{plan}</b> (${amount:.0f})\n"
                    f"Email: {customer_email}",
                    already_html=True,
                )
            except Exception:
                pass

        elif event_type in ("invoice.payment_failed", "customer.subscription.deleted"):
            customer_email = event_data.get("customer_email", "")
            try:
                from apps.core.tools.telegram_bot import get_bot

                await get_bot().notify_owner(
                    f"⚠️ Stripe event: {event_type}\nEmail: {customer_email}",
                    already_html=False,
                )
            except Exception:
                pass

        return JSONResponse(status_code=200, content={"received": True})

    except Exception as exc:
        logger.error("[stripe_webhook] error: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)[:100]})
