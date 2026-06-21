import asyncio
import logging
import os
import sys

from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .telegram.handlers.session import (
    ASK_SESSION,
    setsession_start, setsession_got, session_cancel,
)
from .telegram.handlers.board_selection import cmd_setboard, setboard_callback
from .telegram.handlers.vote_command import cmd_vote
from .telegram.handlers.skip_keywords import (
    ASK_SKIP_ADD, ASK_SKIP_REMOVE,
    cmd_addskip, cmd_removeskip, cmd_listskip,
    addskip_received, removeskip_received, skip_cancel,
)
from .telegram.handlers.run_stats import (
    ASK_TOGGLE_IDX, ASK_DELETE_IDX,
    cmd_stats, cmd_togglestat, cmd_deletestat,
    togglestat_received, deletestat_received, stat_cancel,
)
from .telegram.handlers.basic import cmd_start, cmd_status
from .settings import load_env

load_env()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)

_conflict_count = 0


async def _error_handler(update, context) -> None:
    global _conflict_count
    if isinstance(context.error, Conflict):
        _conflict_count += 1
        if _conflict_count > 3:
            logging.error("Conflict 에러 3회 연속 발생. 봇을 종료합니다.")
            sys.exit(1)
        logging.warning(f"다른 인스턴스가 실행 중입니다. 5초 후 재시도... ({_conflict_count}/3)")
        await asyncio.sleep(5)
    else:
        logging.error(f"처리되지 않은 에러: {context.error}", exc_info=context.error)


def main():
    telegram_token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN 환경변수가 설정되지 않았습니다.")

    app = (
        Application.builder()
        .token(telegram_token)
        .concurrent_updates(True)
        .build()
    )

    session_conv = ConversationHandler(
        entry_points=[CommandHandler("setsession", setsession_start)],
        states={
            ASK_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, setsession_got)],
        },
        fallbacks=[CommandHandler("cancel", session_cancel)],
    )

    addskip_conv = ConversationHandler(
        entry_points=[CommandHandler("addskip", cmd_addskip)],
        states={
            ASK_SKIP_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, addskip_received)],
        },
        fallbacks=[CommandHandler("cancel", skip_cancel)],
    )

    removeskip_conv = ConversationHandler(
        entry_points=[CommandHandler("removeskip", cmd_removeskip)],
        states={
            ASK_SKIP_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, removeskip_received)],
        },
        fallbacks=[CommandHandler("cancel", skip_cancel)],
    )

    togglestat_conv = ConversationHandler(
        entry_points=[CommandHandler("togglestat", cmd_togglestat)],
        states={
            ASK_TOGGLE_IDX: [MessageHandler(filters.TEXT & ~filters.COMMAND, togglestat_received)],
        },
        fallbacks=[CommandHandler("cancel", stat_cancel)],
    )

    deletestat_conv = ConversationHandler(
        entry_points=[CommandHandler("deletestat", cmd_deletestat)],
        states={
            ASK_DELETE_IDX: [MessageHandler(filters.TEXT & ~filters.COMMAND, deletestat_received)],
        },
        fallbacks=[CommandHandler("cancel", stat_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(session_conv)
    app.add_handler(CommandHandler("setboard", cmd_setboard))
    app.add_handler(CallbackQueryHandler(setboard_callback, pattern="^(sb:|bp:)"))
    app.add_handler(CommandHandler("vote", cmd_vote))
    app.add_handler(addskip_conv)
    app.add_handler(removeskip_conv)
    app.add_handler(CommandHandler("listskip", cmd_listskip))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(togglestat_conv)
    app.add_handler(deletestat_conv)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_error_handler(_error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
