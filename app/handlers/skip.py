from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ..repository import get_skip_keywords, save_skip_keywords
from .utils import _authorized

ASK_SKIP_ADD, ASK_SKIP_REMOVE = range(2)


async def _do_addskip(update: Update, kw: str) -> None:
    keywords = get_skip_keywords()
    if kw in keywords:
        await update.message.reply_text(f"⚠️ 이미 등록된 키워드: {kw}")
        return
    keywords.append(kw)
    save_skip_keywords(keywords)
    await update.message.reply_text(f"✅ 추가됨: {kw}  (총 {len(keywords)}개)")


async def _do_removeskip(update: Update, kw: str) -> None:
    keywords = get_skip_keywords()
    if kw not in keywords:
        await update.message.reply_text(f"⚠️ 등록되지 않은 키워드: {kw}")
        return
    keywords.remove(kw)
    save_skip_keywords(keywords)
    await update.message.reply_text(f"✅ 삭제됨: {kw}  (남은 {len(keywords)}개)")


async def cmd_addskip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    if context.args:
        await _do_addskip(update, " ".join(context.args).strip())
        return ConversationHandler.END
    await update.message.reply_text("건너뛸 키워드를 입력해주세요:\n(/cancel 로 취소)")
    return ASK_SKIP_ADD


async def cmd_removeskip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    if context.args:
        await _do_removeskip(update, " ".join(context.args).strip())
        return ConversationHandler.END
    await update.message.reply_text("삭제할 키워드를 입력해주세요:\n(/cancel 로 취소)")
    return ASK_SKIP_REMOVE


async def addskip_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_addskip(update, update.message.text.strip())
    return ConversationHandler.END


async def removeskip_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _do_removeskip(update, update.message.text.strip())
    return ConversationHandler.END


async def skip_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("취소되었습니다.")
    return ConversationHandler.END


async def cmd_listskip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    keywords = get_skip_keywords()
    if not keywords:
        await update.message.reply_text("등록된 키워드가 없습니다.")
        return
    lines = "\n".join(f"• {kw}" for kw in keywords)
    await update.message.reply_text(f"🚫 건너뛸 키워드 ({len(keywords)}개):\n{lines}")
