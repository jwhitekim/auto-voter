import asyncio
import logging
import random
from datetime import date, datetime, time as dt_time, timedelta, timezone

from telegram.ext import Application, ContextTypes

from .vote_runner import VoteRunner
from ..settings import load_config
from ..telegram.handlers.vote_command import _vote_lock
from ..telegram.handlers.shared import _allowed_chat_id
from ..telegram.messages import format_vote_result

KST = timezone(timedelta(hours=9))

WINDOW_A = ((15, 0), (18, 0))
WINDOW_B = ((21, 0), (0, 0))  # 익일로 넘어감

UNREAD_CHECK_WAIT_SECONDS = 2 * 60
ACTIVITY_RETRY_WAIT_RANGE = (5 * 60, 15 * 60)
MAX_ACTIVITY_ATTEMPTS = 3

DAILY_RESCHEDULE_JOB_NAME = "autonomy_daily_reschedule"
TRIGGER_JOB_NAME_PREFIX = "autonomy_trigger_"

SLOT_LABELS = {"A": "오후 슬롯", "B": "야간 슬롯"}
SLOT_EMOJIS = {"A": "☀️", "B": "🌙"}


def _random_dt_in_window(base_date: date, window, crosses_midnight: bool) -> datetime:
    (start_h, start_m), (end_h, end_m) = window
    start_dt = datetime(base_date.year, base_date.month, base_date.day, start_h, start_m, tzinfo=KST)
    end_date = base_date + timedelta(days=1) if crosses_midnight else base_date
    end_dt = datetime(end_date.year, end_date.month, end_date.day, end_h, end_m, tzinfo=KST)
    span_seconds = int((end_dt - start_dt).total_seconds())
    return start_dt + timedelta(seconds=random.randint(0, span_seconds))


def _todays_triggers(base_date: date) -> list[datetime]:
    return [
        _random_dt_in_window(base_date, WINDOW_A, crosses_midnight=False),
        _random_dt_in_window(base_date, WINDOW_B, crosses_midnight=True),
    ]


def _schedule_triggers_for(application: Application, base_date: date) -> None:
    now = datetime.now(KST)
    for slot, when in zip(("A", "B"), _todays_triggers(base_date)):
        if when <= now:
            logging.info(f"[autonomy] {when} 트리거는 이미 지나서 건너뜁니다.")
            continue
        name = f"{TRIGGER_JOB_NAME_PREFIX}{base_date.isoformat()}_{slot}"
        application.job_queue.run_once(
            _run_autonomous_vote, when=when, name=name, data={"slot": slot, "when": when}
        )
        logging.info(f"[autonomy] 트리거 예약: {when.isoformat()} ({name})")


async def _daily_reschedule(context: ContextTypes.DEFAULT_TYPE) -> None:
    _schedule_triggers_for(context.application, datetime.now(KST).date())


async def _wait_for_no_activity(client) -> tuple[bool, int]:
    """활동 없음이 확인되면 (True, 재시도 횟수)를, 포기하면 (False, 재시도 횟수)를 반환."""
    for attempt in range(1, MAX_ACTIVITY_ATTEMPTS + 1):
        c1 = client.get_unread_count()
        await asyncio.sleep(UNREAD_CHECK_WAIT_SECONDS)
        c2 = client.get_unread_count()

        if c1 is not None and c2 is not None and c2 >= c1:
            return True, attempt - 1

        logging.info(f"[autonomy] 활동 감지 또는 조회 실패 (c1={c1}, c2={c2}), 시도 {attempt}/{MAX_ACTIVITY_ATTEMPTS}")
        if attempt == MAX_ACTIVITY_ATTEMPTS:
            logging.info("[autonomy] 최대 재시도 도달, 이번 슬롯은 포기합니다.")
            return False, attempt
        await asyncio.sleep(random.uniform(*ACTIVITY_RETRY_WAIT_RANGE))
    return False, MAX_ACTIVITY_ATTEMPTS


async def _send_report(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    chat_id = _allowed_chat_id()
    if chat_id is None:
        logging.error("[autonomy] chat_id를 확인할 수 없어 결과 메시지를 보내지 못했습니다.")
        return
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logging.error(f"[autonomy] 결과 메시지 전송 실패: {e}")


async def _run_autonomous_vote(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = context.job.data or {}
    slot = job_data.get("slot", "?")
    when: datetime | None = job_data.get("when")
    time_str = when.strftime("%H:%M") if when else "?"
    label = SLOT_LABELS.get(slot, "자동")
    emoji = SLOT_EMOJIS.get(slot, "⏰")

    if _vote_lock.locked():
        logging.info("[autonomy] 수동 /vote 진행 중이라 이번 자동 슬롯은 건너뜁니다.")
        return

    try:
        runner = VoteRunner(load_config())
    except Exception as e:
        logging.error(f"[autonomy] VoteRunner 초기화 실패: {e}")
        await _send_report(context, f"❌ {label} 자동 실행 실패 — {e}")
        return

    no_activity, retries = await _wait_for_no_activity(runner.client)
    if not no_activity:
        await _send_report(
            context,
            f"⏭️ {label}({time_str}) 자동 실행 스킵 — 활동 감지로 {MAX_ACTIVITY_ATTEMPTS}회 재시도 후 포기",
        )
        return

    if _vote_lock.locked():
        logging.info("[autonomy] 대기 중 수동 /vote가 시작되어 이번 자동 슬롯은 건너뜁니다.")
        return

    loop = asyncio.get_running_loop()
    await _vote_lock.acquire()
    try:
        deleted = await loop.run_in_executor(None, runner.delete_my_articles)
        logging.info(f"[autonomy] 본인 게시글 삭제: {deleted}건")
        result = await loop.run_in_executor(None, runner.start)
        logging.info(f"[autonomy] 자동 실행 결과: {result}")
    except Exception as e:
        logging.error(f"[autonomy] 자동 실행 중 오류: {e}")
        await _send_report(context, f"❌ {label} 자동 실행 실패 — {e}")
        return
    finally:
        _vote_lock.release()

    if not result.get("success"):
        await _send_report(context, f"❌ {label} 자동 실행 실패 — 세션이 유효하지 않습니다. /setsession 필요")
        return

    now_str = datetime.now(KST).strftime("%H:%M")
    header = f"{emoji} {label}({time_str}) 자동 실행\n🗑️ 본인 글 삭제: {deleted}개\n"
    if retries:
        header += f"🔁 활동 감지 재시도: {retries}회\n"
    await _send_report(context, header + "\n" + format_vote_result(result, now_str))


def setup_autonomy(application: Application) -> None:
    if application.job_queue is None:
        logging.error("[autonomy] job_queue를 사용할 수 없습니다. python-telegram-bot[job-queue] 설치가 필요합니다.")
        return

    _schedule_triggers_for(application, datetime.now(KST).date())

    application.job_queue.run_daily(
        _daily_reschedule,
        time=dt_time(hour=0, minute=5, tzinfo=KST),
        name=DAILY_RESCHEDULE_JOB_NAME,
    )
