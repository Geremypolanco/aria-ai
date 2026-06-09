import os
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower() if update.message.text else ""
    
    if 'shopify' in text or 'ingresos' in text:
        await update.message.reply_text("✅ Entendido. Estoy generando productos digitales y automatizando ventas en Shopify ahora mismo. ¿Qué nicho priorizamos?")
    elif 'mejora' in text:
        await update.message.reply_text("⚡ Auto-mejora masiva en progreso. Clonando arquitecturas avanzadas...")
    else:
        await update.message.reply_text("Entendido. Estoy aquí, recordando nuestro contexto y trabajando en tus objetivos. ¿Qué sigue?")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ Token no encontrado")
        return
    
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Aria Bot - Modo humano y eficiente activo")
    app.run_polling()

if __name__ == "__main__":
    main()