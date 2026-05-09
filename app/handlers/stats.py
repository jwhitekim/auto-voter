from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ..repository import load_run_history, save_run_history, delete_run_stat
from ..formatter import format_stats_message
from .utils import _authorized

ASK_TOGGLE_IDX, ASK_DELETE_IDX = range(2)


async def _do_togglestat(update: Update, idx: int) -> None:
    history = load_run_history()
    if not history:
        await update.message.reply_text("실행 기록이 없습니다.")
        return
    if not (0 <= idx < len(history)):
        await update.message.reply_text(f"❌ 유효한 번호 범위: 1~{len(history)}")
        return
    history[idx]["is_valid"] = not history[idx].get("is_valid", True)
    save_run_history(history)
    state = "유효" if history[idx]["is_valid"] else "제외"
    await update.message.reply_text(f"✅ #{idx + 1} 레코드를 [{state}]로 변경했습니다.")


async def _do_deletestat(update: Update, idx: int) -> None:
    history = load_run_history()
    if not history:
        await update.message.reply_text("실행 기록이 없습니다.")
        return
    if not (0 <= idx < len(history)):
        await update.message.reply_text(f"❌ 유효한 번호 범위: 1~{len(history)}")
        return
    record = history[idx]
    if delete_run_stat(idx):
        board = record.get("board_name") or record.get("board_id", "")
        await update.message.reply_text(
            f"🗑 #{idx + 1} 레코드 삭제됨\n"
            f"  {record['ran_at'][:16]}  {record['voted']}개  ({board})"
        )
    else:
        await update.message.reply_text("❌ 삭제 실패.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    history = load_run_history()
    if not history:
        await update.message.reply_text("아직 실행 기록이 없습니다.")
        return
    await update.message.reply_text(format_stats_message(history))


async def cmd_togglestat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    if context.args:
        try:
            idx = int(context.args[0]) - 1
        except ValueError:
            await update.message.reply_text("❌ 숫자를 입력해주세요.")
            return ConversationHandler.END
        await _do_togglestat(update, idx)
        return ConversationHandler.END
    await update.message.reply_text("토글할 레코드 번호를 입력해주세요:\n(/cancel 로 취소)")
    return ASK_TOGGLE_IDX


async def cmd_deletestat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    if context.args:
        try:
            idx = int(context.args[0]) - 1
        except ValueError:
            await update.message.reply_text("❌ 숫자를 입력해주세요.")
            return ConversationHandler.END
        await _do_deletestat(update, idx)
        return ConversationHandler.END
    await update.message.reply_text("삭제할 레코드 번호를 입력해주세요:\n(/cancel 로 취소)")
    return ASK_DELETE_IDX


async def togglestat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(update.message.text.strip()) - 1
    except ValueError:
        await update.message.reply_text("❌ 숫자를 입력해주세요.")
        return ASK_TOGGLE_IDX
    await _do_togglestat(update, idx)
    return ConversationHandler.END


async def deletestat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(update.message.text.strip()) - 1
    except ValueError:
        await update.message.reply_text("❌ 숫자를 입력해주세요.")
        return ASK_DELETE_IDX
    await _do_deletestat(update, idx)
    return ConversationHandler.END


async def stat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("취소되었습니다.")
    return ConversationHandler.END
