import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from ...core.vote_runner import VoteRunner
from ...core.database import db
from ...settings import load_config
from .shared import _authorized


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "📋 사용 가능한 명령어:\n"
        "/setsession — etsid 수동 입력\n"
        "/setboard — 공감할 게시판 선택\n"
        "/vote — 공감 봇 실행\n"
        "/addskip 키워드 — 건너뛸 키워드 추가\n"
        "/removeskip 키워드 — 키워드 삭제\n"
        "/listskip — 등록된 키워드 목록\n"
        "/stats — 공감 통계\n"
        "/togglestat <번호> — 레코드 유효/제외 토글\n"
        "/deletestat <번호> — 레코드 영구 삭제\n"
        "/status — 현재 상태 확인"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return

    etsid_saved = db.exists("etsid")
    session_valid = False
    board_name_cached = db.load("board_name")

    if etsid_saved:
        try:
            cfg = load_config()
            loop = asyncio.get_running_loop()
            bot = VoteRunner(cfg)
            session_valid = await loop.run_in_executor(
                None, bot.check_session, bot.target_board
            )
            if not board_name_cached and db.load("board_id"):
                boards = await loop.run_in_executor(None, bot.get_board_list)
                found = next(
                    (b["name"] for b in boards if b["id"] == db.load("board_id")),
                    None,
                )
                if found:
                    db.save("board_name", found)
                    board_name_cached = found
        except Exception:
            pass

    cfg = load_config()
    current_board = (
        board_name_cached
        or db.load("board_id")
        or cfg["bot"]["board_id"]
    )

    await update.message.reply_text(
        f"🔐 세션: {'✅ 저장됨' if etsid_saved else '❌ 없음'}\n"
        f"📡 세션: {'✅ 유효' if session_valid else '❌ 만료/없음'}\n"
        f"📋 게시판: {current_board}\n"
        f"🕐 마지막 실행: {db.load('last_run_time') or '없음'}"
    )
