import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower() if update.message and update.message.text else ""
    if 'shopify' in text or 'ingresos' in text:
        await update.message.reply_text("✅ Entendido. Iniciando generación de ingresos. ¿Qué producto deseas crear primero?")
    elif 'mejora' in text:
        await update.message.reply_text("🔄 Auto-mejora masiva activada. Buscando código avanzado...")
    else:
        await update.message.reply_text("Entendido. Estoy aquí, con memoria completa y lista para actuar. Dime tu siguiente orden.")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Aria Telegram Bot corriendo en modo humano...")
    app.run_polling()

if __name__ == "__main__":
    main()