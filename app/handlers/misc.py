import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..voter import Main, load_config
from ..repository import storage
from .utils import _authorized


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


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return

    etsid_saved = storage.exists("etsid")
    session_valid = False
    board_name_cached = storage.load("board_name")

    if etsid_saved:
        try:
            cfg = load_config()
            loop = asyncio.get_running_loop()
            bot = Main(cfg)
            session_valid = await loop.run_in_executor(
                None, bot.check_session, bot.target_board
            )
            if not board_name_cached and storage.load("board_id"):
                boards = await loop.run_in_executor(None, bot.get_board_list)
                found = next(
                    (b["name"] for b in boards if b["id"] == storage.load("board_id")),
                    None,
                )
                if found:
                    storage.save("board_name", found)
                    board_name_cached = found
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
        board_name_cached
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


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    for key in ("userid", "password", "etsid"):
        storage.delete(key)
    await update.message.reply_text("✅ 저장된 정보가 모두 삭제되었습니다.")
