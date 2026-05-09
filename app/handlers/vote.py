import asyncio
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from ..auth import get_etsid
from ..voter import Main, load_config
from ..repository import storage, get_skip_keywords, append_run_stat
from ..formatter import _fmt_created_at
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
