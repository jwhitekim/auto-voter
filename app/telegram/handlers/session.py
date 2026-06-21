from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ...storage import storage
from .shared import _authorized

ASK_SESSION = 0


async def session_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("취소되었습니다.")
    return ConversationHandler.END


async def setsession_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    await update.message.reply_text(
        "etsid 값을 붙여넣으세요\n"
        "(Chrome DevTools → Application → Cookies → api.everytime.kr → etsid)"
    )
    return ASK_SESSION


async def setsession_got(update: Update, context: ContextTypes.DEFAULT_TYPE):
    etsid = update.message.text.strip()
    for key in ("userid", "password", "browser_state"):
        storage.delete(key)
    storage.save("etsid", etsid)
    await update.message.reply_text("✅ 세션이 저장되었습니다. /vote 로 시작하세요.")
    return ConversationHandler.END
