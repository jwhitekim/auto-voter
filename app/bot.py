import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .auth import get_etsid
from .voter import Main, load_config
from .repository import storage, get_skip_keywords, save_skip_keywords, append_run_stat, load_run_history, save_run_history, delete_run_stat
from .stats import format_stats_message

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

ASK_USER, ASK_PASS, ASK_SESSION = range(3)

_vote_lock = asyncio.Lock()

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
        "/setboard — 공감할 게시판 선택\n"
        "/vote — 공감 봇 실행\n"
        "/addskip 키워드 — 건너뛸 키워드 추가\n"
        "/removeskip 키워드 — 키워드 삭제\n"
        "/listskip — 등록된 키워드 목록\n"
        "/stats — 공감 통계\n"
        "/togglestat <번호> — 레코드 유효/제외 토글\n"
        "/deletestat <번호> — 레코드 영구 삭제\n"
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
    try:
        await update.message.delete()
    except Exception:
        pass

    userid = context.user_data.pop("userid", "")
    msg = await update.effective_chat.send_message("🔄 로그인 중...")
    etsid = await get_etsid(userid, password, storage)

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


# ── /setboard ────────────────────────────────────────────────────────────

def _build_board_keyboard(boards: list[dict], page: int) -> InlineKeyboardMarkup:
    per_page = 10
    start = page * per_page
    end = start + per_page
    rows = [
        [InlineKeyboardButton(b["name"], callback_data=f"sb:{b['id']}")]
        for b in boards[start:end]
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ 이전", callback_data=f"bp:{page - 1}"))
    if end < len(boards):
        nav.append(InlineKeyboardButton("다음 ▶", callback_data=f"bp:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


async def cmd_setboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not storage.exists("etsid"):
        await update.message.reply_text("⚠️ /login 먼저 실행하세요.")
        return

    msg = await update.message.reply_text("🔄 게시판 목록 불러오는 중...")
    loop = asyncio.get_running_loop()
    try:
        cfg = load_config()
        bot = Main(cfg)
        boards = await loop.run_in_executor(None, bot.get_board_list)
    except Exception as e:
        await msg.edit_text(f"❌ 게시판 목록 조회 실패: {e}")
        return

    if not boards:
        await msg.edit_text("❌ 게시판 목록을 가져올 수 없습니다. 세션을 확인하세요.")
        return

    context.user_data["boards"] = boards
    await msg.edit_text("📋 게시판을 선택하세요:", reply_markup=_build_board_keyboard(boards, 0))


async def setboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _authorized(update):
        return

    data = query.data
    if data.startswith("bp:"):
        page = int(data[3:])
        boards = context.user_data.get("boards", [])
        await query.edit_message_reply_markup(reply_markup=_build_board_keyboard(boards, page))
    elif data.startswith("sb:"):
        board_id = data[3:]
        boards = context.user_data.get("boards", [])
        board_name = next((b["name"] for b in boards if b["id"] == board_id), board_id)
        storage.save("board_id", board_id)
        storage.save("board_name", board_name)
        await query.edit_message_text(
            f"✅ 게시판 설정 완료!\n"
            f"📌 {board_name} ({board_id})\n\n"
            f"/vote 로 공감을 시작하세요."
        )


# ── /vote ─────────────────────────────────────────────────────────────────

async def cmd_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not storage.exists("etsid"):
        await update.message.reply_text("⚠️ /login 먼저 실행하세요.")
        return
    if _vote_lock.locked():
        await update.message.reply_text("⚠️ 이미 공감이 실행 중입니다.")
        return

    async with _vote_lock:
        cfg = load_config()
        loop = asyncio.get_running_loop()

        for attempt in range(2):
            try:
                bot = Main(cfg)
            except ValueError:
                await update.message.reply_text("⚠️ /login 먼저 실행하세요.")
                return
            except Exception as e:
                logging.error(f"Main 초기화 실패: {e}")
                return

            try:
                session_ok = await loop.run_in_executor(None, bot.check_session, bot.target_board)
            except Exception as e:
                logging.error(f"check_session 실패: {e}")
                return

            if not session_ok:
                if attempt == 0 and storage.exists("userid") and storage.exists("password"):
                    msg = await update.effective_chat.send_message("🔄 세션 만료. 자동 재로그인 중...")
                    new_etsid = await get_etsid(
                        storage.load("userid"), storage.load("password"), storage
                    )
                    if new_etsid:
                        storage.save("etsid", new_etsid)
                        await msg.edit_text("✅ 재로그인 성공. 공감 시작...")
                        continue
                    else:
                        await msg.edit_text("❌ 재로그인 실패. /login 으로 다시 시도하세요.")
                        return
                else:
                    await update.message.reply_text("❌ 세션이 유효하지 않습니다. /login 을 실행하세요.")
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

            skip_keywords = get_skip_keywords()
            result = await loop.run_in_executor(None, bot.start, _progress, skip_keywords)

            KST = timezone(timedelta(hours=9))
            now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
            storage.save("last_run_time", now_kst)

            if result["success"]:
                processed = result["processed"]
                skipped = result.get("skipped", 0)
                page = result.get("final_page", 1)
                last_created_at = result.get("last_created_at", "")
                last_title = result.get("last_title", "")
                now_str = datetime.now(KST).strftime("%H:%M")
                fmt_ca = _fmt_created_at(last_created_at) if last_created_at else "?"
                if processed > 0 or skipped > 0:
                    append_run_stat(bot.target_board, processed, skipped, now_kst, result.get("is_full_scan"))
                skip_line = f"\n🚫 건너뜀 {skipped}개" if skipped else ""
                if processed == 0:
                    await _safe_edit(msg, (
                        f"✅ 이미 최신 상태입니다\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"📌 {fmt_ca} 이후 새 게시글 없음\n"
                        f"   └ {last_title}\n"
                        f"🕐 {now_str}{skip_line}"
                    ))
                else:
                    await _safe_edit(msg, (
                        f"✅ 공감 완료  |  🆕 신규 +{processed}개\n"
                        f"━━━━━━━━━━━━━━━━ {processed}개\n"
                        f"📄 {page}페이지  |  🕐 {now_str}\n"
                        f"📌 {fmt_ca} 게시글까지\n"
                        f"   └ {last_title}{skip_line}"
                    ))
            else:
                await _safe_edit(msg, "❌ 공감 도중 오류가 발생했습니다.")
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
            bot = Main(cfg)
            session_valid = await asyncio.get_running_loop().run_in_executor(
                None, bot.check_session, bot.target_board
            )
        except Exception:
            pass

    last_title = None
    try:
        cp = Main(load_config()).read_checkpoint()
        last_title = cp.get("post_title") or cp.get("post_id") or None
    except Exception:
        pass

    cfg = load_config()
    current_board = (
        storage.load("board_name")
        or storage.load("board_id")
        or cfg["bot"]["board_id"]
    )

    await update.message.reply_text(
        f"🔐 로그인: {'✅ 저장됨' if etsid_saved else '❌ 없음'}\n"
        f"📡 세션: {'✅ 유효' if session_valid else '❌ 만료/없음'}\n"
        f"📋 게시판: {current_board}\n"
        f"🕐 마지막 실행: {storage.load('last_run_time') or '없음'}\n"
        f"📌 마지막 처리 글: {last_title or '없음'}"
    )


# ── /logout ───────────────────────────────────────────────────────────────

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    for key in ("userid", "password", "etsid"):
        storage.delete(key)
    await update.message.reply_text("✅ 저장된 정보가 모두 삭제되었습니다.")


# ── /addskip /removeskip /listskip ────────────────────────────────────────

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


# ── /stats /togglestat /deletestat ───────────────────────────────────────

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


# ── Entry point ───────────────────────────────────────────────────────────

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
