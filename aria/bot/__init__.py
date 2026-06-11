"""Aria Telegram Bot — handles all incoming messages and commands.

Uses python-telegram-bot v21 (async). Sends messages to the Aria
brain and streams the response back to the user.
"""
import logging
import os

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from aria.brain.agent import AriaAgent
from aria.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Singleton agent & memory (shared across all conversations in this process)
_agent: AriaAgent | None = None
_memory: MemoryStore | None = None


def _get_agent() -> AriaAgent:
    global _agent, _memory
    if _agent is None:
        _memory = MemoryStore()
        _agent = AriaAgent(memory=_memory)
    return _agent


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Hola <b>{user.first_name}</b>! Soy Aria 🧠\n"
        "Soy un sistema autónomo de negocios. ¿En qué puedo ayudarte?"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Comandos disponibles:*\n"
        "/start — Saludo inicial\n"
        "/help — Esta ayuda\n"
        "/memory — Ver resumen de memoria\n"
        "/clear — Limpiar historial de conversación\n"
        "/status — Estado del sistema"
    )
    await update.message.reply_markdown(text)


async def cmd_memory(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    agent = _get_agent()
    user_id = str(update.effective_user.id)
    summary = await agent.memory.get_summary(user_id)
    await update.message.reply_text(summary or "No hay memoria almacenada aún.")


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    agent = _get_agent()
    user_id = str(update.effective_user.id)
    await agent.memory.clear(user_id)
    await update.message.reply_text("✅ Historial limpiado.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    agent = _get_agent()
    status = await agent.get_status()
    await update.message.reply_markdown(status)


# ---------------------------------------------------------------------------
# Message Handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    text = update.message.text

    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    agent = _get_agent()
    try:
        response = await agent.run(user_id=user_id, message=text)
    except Exception as exc:
        logger.exception("Agent error for user %s: %s", user_id, exc)
        response = "⚠️ Ocurrió un error interno. Inténtalo de nuevo."

    # Telegram messages max 4096 chars — split if needed
    for chunk in _split_text(response):
        await update.message.reply_text(chunk)


def _split_text(text: str, max_len: int = 4000) -> list[str]:
    """Split a long string into Telegram-safe chunks."""
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


# ---------------------------------------------------------------------------
# Error Handler
# ---------------------------------------------------------------------------

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception:", exc_info=ctx.error)


# ---------------------------------------------------------------------------
# App Builder
# ---------------------------------------------------------------------------

def build_application() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    logger.info("Telegram application built with token ...%s", token[-6:])
    return app
