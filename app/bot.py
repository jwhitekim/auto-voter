import logging
import os

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .handlers.auth import (
    ASK_USER, ASK_PASS, ASK_SESSION,
    login_start, login_got_user, login_got_pass, login_cancel,
    setsession_start, setsession_got,
)
from .handlers.board import cmd_setboard, setboard_callback
from .handlers.vote import cmd_vote
from .handlers.skip import (
    ASK_SKIP_ADD, ASK_SKIP_REMOVE,
    cmd_addskip, cmd_removeskip, cmd_listskip,
    addskip_received, removeskip_received, skip_cancel,
)
from .handlers.stats import (
    ASK_TOGGLE_IDX, ASK_DELETE_IDX,
    cmd_stats, cmd_togglestat, cmd_deletestat,
    togglestat_received, deletestat_received, stat_cancel,
)
from .handlers.misc import cmd_start, cmd_status, cmd_logout

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            ASK_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_got_user)],
            ASK_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_got_pass)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )

    session_conv = ConversationHandler(
        entry_points=[CommandHandler("setsession", setsession_start)],
        states={
            ASK_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, setsession_got)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
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
    app.add_handler(login_conv)
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
    app.add_handler(CommandHandler("logout", cmd_logout))

    app.run_polling()


if __name__ == "__main__":
    main()
