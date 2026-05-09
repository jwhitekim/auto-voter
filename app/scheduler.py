import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from .auth import get_etsid
from .voter import Main, load_config
from .repository import storage, get_skip_keywords, append_run_stat

load_dotenv()
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])

_scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
_vote_lock = asyncio.Lock()


def update_scheduler(app, hour: int, minute: int) -> None:
    if not _scheduler.running:
        _scheduler.start()
    _scheduler.remove_all_jobs()
    _scheduler.add_job(
        run_scheduled_vote,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        args=[app],
        id="auto_vote",
        replace_existing=True,
    )


async def run_scheduled_vote(app) -> None:
    logging.info("스케줄 자동 실행 시작")
    if not storage.exists("etsid"):
        await app.bot.send_message(ALLOWED_CHAT_ID, "⏰ 자동 실행 실패: /login 먼저 실행하세요.")
        return

    if _vote_lock.locked():
        logging.info("스케줄 실행 건너뜀: 이미 vote 진행 중")
        return

    async with _vote_lock:
        cfg = load_config()
        loop = asyncio.get_running_loop()
        try:
            bot = Main(cfg)
            session_ok = await loop.run_in_executor(None, bot.check_session, bot.target_board)
            if not session_ok:
                if storage.exists("userid") and storage.exists("password"):
                    new_etsid = await get_etsid(
                        storage.load("userid"), storage.load("password"), storage
                    )
                    if new_etsid:
                        storage.save("etsid", new_etsid)
                        bot = Main(cfg)
                    else:
                        await app.bot.send_message(
                            ALLOWED_CHAT_ID, "⏰ 자동 실행 실패: 재로그인 실패. /login 을 실행하세요."
                        )
                        return
                else:
                    await app.bot.send_message(
                        ALLOWED_CHAT_ID, "⏰ 자동 실행 실패: 세션 만료. /login 을 실행하세요."
                    )
                    return

            skip_keywords = get_skip_keywords()
            result = await loop.run_in_executor(None, bot.start, None, skip_keywords)

            KST = timezone(timedelta(hours=9))
            now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
            storage.save("last_run_time", now_kst)
            now_str = datetime.now(KST).strftime("%H:%M")

            if result["success"]:
                voted = result["processed"]
                skipped = result.get("skipped", 0)
                if voted > 0 or skipped > 0:
                    append_run_stat(bot.target_board, voted, skipped, now_kst, result.get("is_full_scan"))
                board_label = storage.load("board_name") or bot.target_board
                if voted == 0:
                    msg = f"⏰ 자동 실행 — 새 게시글 없음 ({now_str})\n📋 {board_label}"
                else:
                    msg = f"⏰ 자동 실행 완료 — +{voted}개 공감"
                    if skipped:
                        msg += f" / {skipped}개 건너뜀"
                    msg += f" ({now_str})\n📋 {board_label}"
                await app.bot.send_message(ALLOWED_CHAT_ID, msg)
            else:
                await app.bot.send_message(ALLOWED_CHAT_ID, "⏰ 자동 실행 오류가 발생했습니다.")
        except Exception as e:
            logging.error(f"스케줄 실행 오류: {e}")
            await app.bot.send_message(ALLOWED_CHAT_ID, f"⏰ 자동 실행 오류: {e}")
