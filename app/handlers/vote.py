import asyncio
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import get_etsid
from ..domain.vote_runner import VoteRunner
from ..repository import storage, get_skip_keywords, append_run_stat
from ..settings import load_config
from ..telegram.messages import format_vote_result
from .utils import _authorized, _safe_edit

_vote_lock = asyncio.Lock()


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
                bot = VoteRunner(cfg)
            except ValueError:
                await update.message.reply_text("⚠️ /login 먼저 실행하세요.")
                return
            except Exception as e:
                logging.error(f"Main 초기화 실패: {e}")
                await update.message.reply_text(f"❌ 초기화 실패: {e}")
                return

            try:
                session_ok = await loop.run_in_executor(None, bot.check_session, bot.target_board)
            except Exception as e:
                logging.error(f"check_session 실패: {e}")
                await update.message.reply_text("❌ 세션 확인 중 오류가 발생했습니다.")
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

            msg = await update.effective_chat.send_message(
                "⏳ 공감 준비 중...\n"
                "1) 이전 실행 기준 게시글 찾는 중\n"
                "2) 찾은 범위에서 공감 후보 정리\n"
                "3) 실제 공감 요청"
            )

            def _progress(n: int, page: int) -> None:
                if n % 5 != 0:
                    return
                fut = asyncio.run_coroutine_threadsafe(
                    _safe_edit(
                        msg,
                        f"⏳ 공감 진행 중...\n"
                        f"✅ 성공 {n}개\n"
                        f"📄 {page}페이지 범위 처리 중",
                    ),
                    loop,
                )
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
                already = result.get("already", 0)
                failed = result.get("failed", 0)
                now_str = datetime.now(KST).strftime("%H:%M")
                if processed > 0 or skipped > 0 or already > 0 or failed > 0:
                    append_run_stat(bot.target_board, processed, skipped, now_kst, None)
                await _safe_edit(msg, format_vote_result(result, now_str))
            else:
                await _safe_edit(msg, "❌ 공감 도중 오류가 발생했습니다.")
            return
