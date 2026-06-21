import asyncio
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import get_etsid
from ..voter import Main, load_config
from ..repository import storage, get_skip_keywords, append_run_stat
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
                bot = Main(cfg)
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
                candidates = result.get("candidates", 0)
                scanned = result.get("scanned", 0)
                page = result.get("final_page", 1)
                checkpoint_found = result.get("checkpoint_found", False)
                scan_limit_reached = result.get("scan_limit_reached", False)
                is_initial = result.get("is_initial", False)
                now_str = datetime.now(KST).strftime("%H:%M")
                if processed > 0 or skipped > 0 or already > 0 or failed > 0:
                    append_run_stat(bot.target_board, processed, skipped, now_kst, None)

                if is_initial:
                    scan_line = f"🔎 초기 스캔: {page}페이지, 게시글 {scanned}개"
                elif checkpoint_found:
                    scan_line = f"🔎 이전 기준 게시글 찾음: {page}페이지, 게시글 {scanned}개 확인"
                elif scan_limit_reached:
                    max_posts = page * 20
                    scan_line = f"⚠️ 이전 기준 게시글 못 찾음: 최대 {page}페이지/{max_posts}개 범위만 처리"
                else:
                    scan_line = f"⚠️ 이전 기준 게시글 못 찾음: {page}페이지/{scanned}개 확인"

                result_lines = [
                    f"✅ 공감 완료: +{processed}개",
                    f"📌 후보: {candidates}개",
                    f"🚫 건너뜀: {skipped}개",
                ]
                if already:
                    result_lines.append(f"↩️ 이미 공감: {already}개")
                if failed:
                    result_lines.append(f"❌ 실패: {failed}개")

                status = "⚠️ 일부 실패" if failed else "✅ 완료"
                if processed == 0 and candidates == 0:
                    status = "✅ 새 공감 후보 없음"
                elif processed == 0 and skipped > 0 and failed == 0:
                    status = "✅ 공감할 글 없음"

                checkpoint_line = (
                    "체크포인트: 실패가 있어 유지됨"
                    if failed else
                    "체크포인트: 이번 최신 글로 갱신됨"
                )

                await _safe_edit(msg, (
                    f"{status}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"{scan_line}\n"
                    + "\n".join(result_lines) +
                    f"\n🕐 {now_str}\n"
                    f"{checkpoint_line}"
                ))
            else:
                await _safe_edit(msg, "❌ 공감 도중 오류가 발생했습니다.")
            return
