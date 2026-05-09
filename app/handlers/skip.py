from telegram import Update
from telegram.ext import ContextTypes

from ..repository import get_skip_keywords, save_skip_keywords
from .utils import _authorized


async def cmd_addskip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: /addskip 키워드")
        return
    kw = " ".join(context.args).strip()
    keywords = get_skip_keywords()
    if kw in keywords:
        await update.message.reply_text(f"⚠️ 이미 등록된 키워드: {kw}")
        return
    keywords.append(kw)
    save_skip_keywords(keywords)
    await update.message.reply_text(f"✅ 추가됨: {kw}  (총 {len(keywords)}개)")


async def cmd_removeskip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: /removeskip 키워드")
        return
    kw = " ".join(context.args).strip()
    keywords = get_skip_keywords()
    if kw not in keywords:
        await update.message.reply_text(f"⚠️ 등록되지 않은 키워드: {kw}")
        return
    keywords.remove(kw)
    save_skip_keywords(keywords)
    await update.message.reply_text(f"✅ 삭제됨: {kw}  (남은 {len(keywords)}개)")


async def cmd_listskip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    keywords = get_skip_keywords()
    if not keywords:
        await update.message.reply_text("등록된 키워드가 없습니다.")
        return
    lines = "\n".join(f"• {kw}" for kw in keywords)
    await update.message.reply_text(f"🚫 건너뛸 키워드 ({len(keywords)}개):\n{lines}")
