import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

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

from .auth import get_etsid
from .voter import Main, load_config
from .storage import SecureStorage

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

# ConversationHandler states
ASK_USER, ASK_PASS, ASK_SESSION = range(3)

storage = SecureStorage()
_last_run_time: str | None = None
_last_bot: "Main | None" = None


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(self.format(record))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logging.getLogger("httpx").setLevel(logging.WARNING)

def _authorized(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


def _fmt_created_at(s: str) -> str:
    """'2026-05-04 20:30:01' → '5/4 오후 8:30'"""
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        ampm = "오전" if dt.hour < 12 else "오후"
        h12 = dt.hour % 12 or 12
        return f"{dt.month}/{dt.day} {ampm} {h12}:{dt.minute:02d}"
    except Exception:
        return s


async def _safe_edit(msg, text: str) -> None:
    for _ in range(2):
        try:
            await msg.edit_text(text)
            return
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                await asyncio.sleep(1)
            else:
                return


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

        checkpoint = bot.read_checkpoint()

        init_lines = ["⏳ 공감 진행 중...", "━━━━░░░░░░░░░░░░ 0개", "📄 1페이지 탐색 중"]
        if checkpoint.get("post_created_at"):
            init_lines.append(f"🔖 {_fmt_created_at(checkpoint['post_created_at'])} 이후 게시글만 탐색")
        msg = await update.effective_chat.send_message("\n".join(init_lines))

        def _progress(n: int, page: int) -> None:
            if n % 5 != 0:
                return
            lines = ["⏳ 공감 진행 중...", f"━━━━░░░░░░░░░░░░ {n}개", f"📄 {page}페이지 탐색 중"]
            if checkpoint.get("post_created_at"):
                lines.append(f"🔖 {_fmt_created_at(checkpoint['post_created_at'])} 이후 게시글만 탐색")
            fut = asyncio.run_coroutine_threadsafe(_safe_edit(msg, "\n".join(lines)), loop)
            try:
                fut.result(timeout=10)
            except Exception:
                pass

        log_handler = ListHandler()
        log_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(log_handler)
        try:
            result = await loop.run_in_executor(None, bot.start, _progress)
        finally:
            root_logger.removeHandler(log_handler)

        global _last_run_time, _last_bot
        _last_run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _last_bot = bot

        if result["success"]:
            processed = result["processed"]
            page = result.get("final_page", 1)
            last_created_at = result.get("last_created_at", "")
            last_title = result.get("last_title", "")
            kst = timezone(timedelta(hours=9))
            now_str = datetime.now(kst).strftime("%H:%M")
            fmt_ca = _fmt_created_at(last_created_at) if last_created_at else "?"
            await _safe_edit(msg, (
                f"✅ 공감 완료  |  🆕 신규 +{processed}개\n"
                f"━━━━━━━━━━━━━━━━ {processed}개\n"
                f"📄 {page}페이지  |  🕐 {now_str}\n"
                f"📌 {fmt_ca} 게시글까지\n"
                f"   └ {last_title}"
            ))
        else:
            await _safe_edit(msg, "❌ 공감 도중 오류가 발생했습니다.")

        log_lines = log_handler.records[-20:]
        if log_lines:
            await update.effective_chat.send_message(
                "📋 실행 로그:\n```\n" + "\n".join(log_lines) + "\n```",
                parse_mode="Markdown",
            )
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

    last_title = None
    try:
        cfg = load_config()
        _tmp = Main(cfg)
        cp = _tmp.read_checkpoint()
        last_title = cp.get("post_title") or cp.get("post_id") or None
    except Exception:
        pass

    await update.message.reply_text(
        f"🔐 로그인: {'✅ 저장됨' if etsid_saved else '❌ 없음'}\n"
        f"📡 세션: {'✅ 유효' if session_valid else '❌ 만료/없음'}\n"
        f"🕐 마지막 실행: {_last_run_time or '없음'}\n"
        f"📌 마지막 처리 글: {last_title or '없음'}"
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
