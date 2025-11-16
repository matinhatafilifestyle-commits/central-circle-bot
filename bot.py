# bot.py
import os
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- Config ----------------
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID")) if os.environ.get("ADMIN_ID") else None
DATABASE_URL = os.environ.get("DATABASE_URL")

if not TG_BOT_TOKEN:
    raise SystemExit("Environment variable TG_BOT_TOKEN is required")

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- Database ----------------
Base = declarative_base()
engine = create_engine(
    DATABASE_URL if DATABASE_URL else "sqlite:///bot.db",
    connect_args={"check_same_thread": False} if not DATABASE_URL else {}
)
SessionLocal = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    name = Column(String, nullable=True)
    join_date = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)
    score = Column(Integer, default=0)
    is_muted = Column(Boolean, default=False)

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    run_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(engine)

# ---------------- Helpers ----------------
def db_add_user(tg_user):
    db = SessionLocal()
    now = datetime.datetime.utcnow()
    u = db.query(User).filter_by(tg_id=tg_user.id).first()
    if not u:
        u = User(
            tg_id=tg_user.id,
            username=getattr(tg_user, "username", None),
            name=tg_user.full_name,
            join_date=now,
            last_active=now,
        )
        db.add(u)
    else:
        u.last_active = now
    db.commit()
    db.close()

def schedule_check_reminders(app):
    db = SessionLocal()
    now = datetime.datetime.utcnow()
    rows = db.query(Reminder).filter(Reminder.run_at <= now).all()
    for r in rows:
        try:
            app.bot.send_message(chat_id=r.chat_id, text=f"🔔 یادآوری: {r.text}")
            db.delete(r)
            db.commit()
        except Exception:
            logger.exception("Reminder send error")
    db.close()

def get_inactive_users(days=7):
    db = SessionLocal()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    rows = db.query(User).filter(User.last_active < cutoff).all()
    db.close()
    return rows

# ---------------- Commands ----------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_add_user(user)
    await update.message.reply_text(
        "سلام! ربات دایره فعال شد.\nبرای لیست دستورات /help را بزنید."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "/start - خوش‌آمد\n"
        "/help - لیست دستورات\n"
        "/remind YYYY-MM-DD_HH:MM متن\n"
        "/status - گزارش فعالیت\n"
        "/poll سوال | گز1 | گز2 | ...\n"
        "/suggest_kick @user دلیل\n"
        "/inactive - اعضای غیرفعال\n"
        "/scoreboard - جدول امتیاز\n"
    )
    await update.message.reply_text(txt)

async def remind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("فرمت صحیح: /remind YYYY-MM-DD_HH:MM جلسه مهم")

    dt_str = args[0].replace("_", " ")
    text = " ".join(args[1:])
    try:
        run_at = datetime.datetime.fromisoformat(dt_str)
    except Exception:
        return await update.message.reply_text("فرمت تاریخ اشتباه است.")

    db = SessionLocal()
    r = Reminder(chat_id=update.effective_chat.id, text=text, run_at=run_at)
    db.add(r)
    db.commit()
    db.close()

    await update.message.reply_text(f"یادآوری ثبت شد برای: {run_at}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("اجازه ندارید.")

    db = SessionLocal()
    rows = db.query(User).order_by(User.last_active.desc()).limit(30).all()
    db.close()

    msg = "آخرین فعالیت‌ها:\n"
    for r in rows:
        msg += f"- {r.name or r.username} — {r.last_active:%Y-%m-%d %H:%M}\n"

    await update.message.reply_text(msg)

async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    if "|" not in raw:
        return await update.message.reply_text("فرمت: /poll سوال | گز1 | گز2")

    parts = raw.split("|")
    question = parts[0].strip()
    options = [x.strip() for x in parts[1:] if x.strip()]

    if len(options) < 2:
        return await update.message.reply_text("حداقل دو گزینه لازم است.")

    await update.effective_chat.send_poll(
        question=question, options=options, is_anonymous=False
    )

async def suggest_kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        return await update.message.reply_text("فرمت: /suggest_kick @user دلیل")

    target = context.args[0]
    reason = " ".join(context.args[1:]) or "بدون دلیل"

    await update.message.reply_text(
        f"📌 پیشنهاد حذف ثبت شد:\n{target}\nدلیل: {reason}\n(لیدر تصمیم‌گیرنده است)"
    )

async def inactive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("فقط لیدر مجاز است.")

    rows = get_inactive_users(7)
    if not rows:
        return await update.message.reply_text("عضو غیرفعال نداریم.")

    txt = "غیرفعال‌های ۷ روز اخیر:\n" + "\n".join(
        f"- {r.name or r.username} — آخرین فعالیت: {r.last_active:%Y-%m-%d}"
        for r in rows
    )

    await update.message.reply_text(txt)

async def scoreboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    rows = db.query(User).order_by(User.score.desc()).limit(20).all()
    db.close()

    if not rows:
        return await update.message.reply_text("هیچ امتیازی ثبت نشده.")

    txt = "📊 جدول امتیازات:\n"
    for i, r in enumerate(rows, 1):
        txt += f"{i}. {r.name or r.username} — {r.score}\n"

    await update.message.reply_text(txt)

async def any_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_add_user(user)

    db = SessionLocal()
    u = db.query(User).filter_by(tg_id=user.id).first()
    if u:
        u.score += 1
        db.commit()
    db.close()

# ---------------- Main ----------------
def main():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("remind", remind_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("poll", poll_cmd))
    app.add_handler(CommandHandler("suggest_kick", suggest_kick_cmd))
    app.add_handler(CommandHandler("inactive", inactive_cmd))
    app.add_handler(CommandHandler("scoreboard", scoreboard_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_msg))

    # Scheduler (خارج از async → بدون مشکل)
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: schedule_check_reminders(app), "interval", seconds=30)
    scheduler.start()

    # Run bot
    app.run_polling()

if __name__ == "__main__":
    main()
