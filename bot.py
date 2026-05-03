import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from auth import get_etsid
from everytime import Main, load_config
from storage import SecureStorage

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

# ConversationHandler states
ASK_USER, ASK_PASS, ASK_SESSION = range(3)

storage = SecureStorage()
_last_run_time: str | None = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def _authorized(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


# ── /start ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "📋 사용 가능한 명령어:\n"
        "/login — 아이디/비번으로 자동 로그인\n"
        "/setsession — etsid 수동 입력\n"
        "/vote — 공감 봇 실행\n"
        "/status — 현재 상태 확인\n"
        "/logout — 저장된 정보 삭제"
    )


# ── /login (ConversationHandler) ──────────────────────────────────────────

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    await update.message.reply_text("아이디를 입력하세요:")
    return ASK_USER


async def login_got_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["userid"] = update.message.text.strip()
    await update.message.reply_text("비밀번호를 입력하세요:")
    return ASK_PASS


async def login_got_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()

    # 보안을 위해 비밀번호 메시지 즉시 삭제
    try:
        await update.message.delete()
    except Exception:
        pass

    userid = context.user_data.pop("userid", "")
    msg = await update.effective_chat.send_message("🔄 로그인 중...")

    etsid = await get_etsid(userid, password)

    if etsid:
        storage.save("userid", userid)
        storage.save("password", password)
        storage.save("etsid", etsid)
        await msg.edit_text("✅ 로그인 완료! /vote 로 시작하세요.")
    else:
        await msg.edit_text(
            "❌ 로그인 실패. 아이디/비번을 확인하거나\n"
            "/setsession 으로 수동 입력하세요."
        )

    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("취소되었습니다.")
    return ConversationHandler.END


# ── /setsession (ConversationHandler) ────────────────────────────────────

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
    storage.save("etsid", etsid)
    await update.message.reply_text("✅ 세션이 저장되었습니다. /vote 로 시작하세요.")
    return ConversationHandler.END


# ── /vote ─────────────────────────────────────────────────────────────────

async def cmd_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _last_run_time
    if not _authorized(update):
        return

    if not storage.exists("etsid"):
        await update.message.reply_text("⚠️ /login 먼저 실행하세요.")
        return

    cfg = load_config()
    loop = asyncio.get_running_loop()

    for attempt in range(2):
        try:
            bot = Main(cfg)
            print(f"[DEBUG] Main 초기화 성공, etsid: {bot.session.headers.get('Cookie')}")
        except ValueError as e:
            print(f"[DEBUG] Main 초기화 ValueError: {e}")
            await update.message.reply_text("⚠️ /login 먼저 실행하세요.")
            return
        except Exception as e:
            print(f"[DEBUG] Main 초기화 예외: {e}")
            return


        print("[DEBUG] check_session 호출 직전")
        try:
            session_ok = await loop.run_in_executor(
                None, bot.check_session, bot.target_board
            )
            print(f"[DEBUG] check_session 결과: {session_ok}")
        except Exception as e:
            print(f"[DEBUG] run_in_executor 예외: {e}")
            return

        if not session_ok:
            if attempt == 0 and storage.exists("userid") and storage.exists("password"):
                msg = await update.effective_chat.send_message(
                    "🔄 세션 만료. 자동 재로그인 중..."
                )
                new_etsid = await get_etsid(
                    storage.load("userid"),
                    storage.load("password"),
                )
                if new_etsid:
                    storage.save("etsid", new_etsid)
                    await msg.edit_text("✅ 재로그인 성공. 공감 시작...")
                    continue
                else:
                    await msg.edit_text(
                        "❌ 재로그인 실패. /login 으로 다시 시도하세요."
                    )
                    return
            else:
                await update.message.reply_text(
                    "❌ 세션이 유효하지 않습니다. /login 을 실행하세요."
                )
                return

        msg = await update.effective_chat.send_message("⏳ 공감 진행 중...")
        result = await loop.run_in_executor(None, bot.start)
        _last_run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if result["success"]:
            await msg.edit_text(
                f"✅ 완료: {result['processed']}개 게시글 공감\n"
                f"마지막 처리 ID: {result['last_id']}"
            )
        else:
            await msg.edit_text("❌ 공감 도중 오류가 발생했습니다.")
        return


# ── /status ───────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return

    etsid_saved = storage.exists("etsid")
    session_valid = False

    if etsid_saved:
        try:
            cfg = load_config()
            loop = asyncio.get_running_loop()
            bot = Main(cfg)
            session_valid = await loop.run_in_executor(
                None, bot.check_session, bot.target_board
            )
        except Exception:
            pass

    last_id = None
    try:
        cfg = load_config()
        with open(cfg["state"]["last_article_file"], "r") as f:
            last_id = f.readline().strip() or None
    except FileNotFoundError:
        pass

    await update.message.reply_text(
        f"🔐 로그인: {'✅ 저장됨' if etsid_saved else '❌ 없음'}\n"
        f"📡 세션: {'✅ 유효' if session_valid else '❌ 만료/없음'}\n"
        f"🕐 마지막 실행: {_last_run_time or '없음'}\n"
        f"📌 마지막 처리 ID: {last_id or '없음'}"
    )


# ── /logout ───────────────────────────────────────────────────────────────

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    for key in ("userid", "password", "etsid"):
        storage.delete(key)
    await update.message.reply_text("✅ 저장된 정보가 모두 삭제되었습니다.")


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

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
    app.add_handler(CommandHandler("vote", cmd_vote))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("logout", cmd_logout))

    app.run_polling()


if __name__ == "__main__":
    main()
