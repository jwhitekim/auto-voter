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
from .handlers.skip import cmd_addskip, cmd_removeskip, cmd_listskip
from .handlers.stats import cmd_stats, cmd_togglestat, cmd_deletestat
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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(login_conv)
    app.add_handler(session_conv)
    app.add_handler(CommandHandler("setboard", cmd_setboard))
    app.add_handler(CallbackQueryHandler(setboard_callback, pattern="^(sb:|bp:)"))
    app.add_handler(CommandHandler("vote", cmd_vote))
    app.add_handler(CommandHandler("addskip", cmd_addskip))
    app.add_handler(CommandHandler("removeskip", cmd_removeskip))
    app.add_handler(CommandHandler("listskip", cmd_listskip))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("togglestat", cmd_togglestat))
    app.add_handler(CommandHandler("deletestat", cmd_deletestat))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("logout", cmd_logout))

    app.run_polling()


if __name__ == "__main__":
    main()
