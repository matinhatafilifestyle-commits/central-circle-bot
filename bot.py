# bot.py
import os
import logging
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# ------------- Config -------------
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID")) if os.environ.get("ADMIN_ID") else None
DATABASE_URL = os.environ.get("DATABASE_URL")  # optional; if not set, sqlite local used

if not TG_BOT_TOKEN:
    raise SystemExit("Environment variable TG_BOT_TOKEN is required")

# ------------- Logging -------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------- Database -------------
Base = declarative_base()
engine = create_engine(DATABASE_URL) if DATABASE_URL else create_engine("sqlite:///bot.db", connect_args={"check_same_thread": False})
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

# ------------- Helpers -------------
def db_add_user(tg_user):
    db = SessionLocal()
    u = db.query(User).filter_by(tg_id=tg_user.id).first()
    now = datetime.datetime.utcnow()
    if not u:
        u = User(tg_id=tg_user.id, username=getattr(tg_user, "username", None),
                 name=tg_user.full_name, join_date=now, last_active=now)
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
            logger.exception("send err")
    db.close()

def get_inactive_users(days=7):
    db = SessionLocal()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    rows = db.query(User).filter(User.last_active < cutoff).all()
    db.close()
    return rows

# ------------- Command Handlers -------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_add_user(user)
    await update.message.reply_text(
        "سلام! به دایره مرکزی خوش اومدی.\nاین ربات به مدیریت گروه کمک می‌کنه. برای دیدن دستورها /help رو بزن."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "/start - ثبت و خوش‌آمد\n"
        "/help - این پیام\n"
        "/remind YYYY-MM-DD_HH:MM متن - زمان‌بندی یادآوری (برای لیدر و یا در گروه)\n"
        "/status - گزارش آخرین اعضا (فقط لیدر)\n"
        "/poll سوال | گز1 | گز2 | ... - ساخت رأی‌گیری ساده (غیرمخفی)\n"
        "/suggest_kick @username دلیل - پیشنهاد حذف (ذخیره و اطلاع‌رسانی)\n"
        "/inactive - لیست اعضای غیرفعال (فقط لیدر)\n"
        "/scoreboard - نمایش نمرات\n"
    )
    await update.message.reply_text(txt)

async def remind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("فرمت: /remind YYYY-MM-DD_HH:MM متن یادآوری (مثال: /remind 2025-11-25_19:00 جلسه)")
        return
    dt_str = args[0].replace("_"," ")
    text = " ".join(args[1:])
    try:
        run_at = datetime.datetime.fromisoformat(dt_str)
    except Exception:
        await update.message.reply_text("فرمت تاریخ اشتباه. مثال: /remind 2025-11-20_19:00 جلسه داریم")
        return
    db = SessionLocal()
    r = Reminder(chat_id=chat_id, text=text, run_at=run_at)
    db.add(r); db.commit(); db.close()
    await update.message.reply_text(f"یادآوری زمان‌بندی شد برای {run_at.isoformat()}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if ADMIN_ID and caller.id != ADMIN_ID:
        await update.message.reply_text("فقط لیدر مجاز به این دستور است.")
        return
    db = SessionLocal()
    rows = db.query(User).order_by(User.last_active.desc()).limit(30).all()
    msg = "آخرین اعضای فعال:\n"
    for r in rows:
        msg += f"- {r.name or r.username} — {r.last_active.strftime('%Y-%m-%d %H:%M')}\n"
    db.close()
    await update.message.reply_text(msg)

async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    if not raw:
        await update.message.reply_text("فرمت: /poll سوال | گز1 | گز2 | ...")
        return
    parts = raw.split("|")
    question = parts[0].strip()
    options = [p.strip() for p in parts[1:] if p.strip()]
    if len(options) < 2:
        await update.message.reply_text("حداقل دو گزینه لازم است.")
        return
    await update.effective_chat.send_poll(question=question, options=options, is_anonymous=False)

async def suggest_kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("فرمت: /suggest_kick @username دلیل")
        return
    target = context.args[0]
    reason = " ".join(context.args[1:]) or "بدون دلیل"
    await update.message.reply_text(f"📌 پیشنهاد حذف ثبت شد: {target}\nدلیل: {reason}\n(لیدر لطفا رأی‌گیری را اجرا کند)")

async def inactive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if ADMIN_ID and caller.id != ADMIN_ID:
        await update.message.reply_text("فقط لیدر مجاز به این دستور است.")
        return
    rows = get_inactive_users(days=7)
    if not rows:
        await update.message.reply_text("آیتم غیرفعالی وجود ندارد (7 روز اخیر).")
        return
    txt = "اعضای غیرفعال (7 روز):\n" + "\n".join([f"- {r.name or r.username} (آخرین فعالیت: {r.last_active.strftime('%Y-%m-%d')})" for r in rows])
    await update.message.reply_text(txt)

async def scoreboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    rows = db.query(User).order_by(User.score.desc()).limit(20).all()
    if not rows:
        await update.message.reply_text("هنوز امتیازی ثبت نشده.")
        db.close(); return
    txt = "📊 جدول امتیازها:\n"
    for i, r in enumerate(rows, 1):
        txt += f"{i}. {r.name or r.username} — {r.score}\n"
    db.close()
    await update.message.reply_text(txt)

async def any_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_add_user(user)
    # Optionally increment score for messages (simple rule)
    db = SessionLocal()
    u = db.query(User).filter_by(tg_id=user.id).first()
    if u:
        u.score += 1
        db.commit()
    db.close()

# ------------- Main -------------
async def main():
    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("remind", remind_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("poll", poll_cmd))
    app.add_handler(CommandHandler("suggest_kick", suggest_kick_cmd))
    app.add_handler(CommandHandler("inactive", inactive_cmd))
    app.add_handler(CommandHandler("scoreboard", scoreboard_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), any_msg))

    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: schedule_check_reminders(app), 'interval', seconds=30)
    scheduler.start()

    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
