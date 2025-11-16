import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN = int(os.getenv("ADMIN_ID"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات مدیریت گروه فعال شد ✔️")

async def all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "supergroup":
        return

    text = update.message.text

    # مثال مدیریت
    bad_words = ["کس", "کیر", "کون", "عوضی"]

    if any(bad in text for bad in bad_words):
        await update.message.delete()
        await context.bot.send_message(update.message.chat_id, "⛔ لطفاً رعایت ادب را بفرمایید.")
        return

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, all_messages))

app.run_polling()
