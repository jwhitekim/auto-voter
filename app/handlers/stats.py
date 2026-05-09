from telegram import Update
from telegram.ext import ContextTypes

from ..repository import load_run_history, save_run_history, delete_run_stat
from ..formatter import format_stats_message
from .utils import _authorized


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
        return
    if not context.args:
        await update.message.reply_text("사용법: /togglestat <번호>  (예: /togglestat 3)")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("❌ 숫자를 입력해주세요.")
        return

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


async def cmd_deletestat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not context.args:
        await update.message.reply_text("사용법: /deletestat <번호>  (예: /deletestat 3)")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("❌ 숫자를 입력해주세요.")
        return

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
