from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ..storage import load_run_history, save_run_history, delete_run_stat
from .shared import _authorized

ASK_TOGGLE_IDX, ASK_DELETE_IDX = range(2)
KST = timezone(timedelta(hours=9))


def _parse_ran_at_kst(ran_at: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ran_at[:19], fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def _format_stats_message(history: list[dict]) -> str:
    valid = [h for h in history if h.get("is_valid", True)]
    if not valid:
        return "유효한 실행 기록이 없습니다."

    now_kst = datetime.now(KST)
    today = now_kst.date()
    week_start = today - timedelta(days=today.weekday())

    today_records = [h for h in valid if (dt := _parse_ran_at_kst(h["ran_at"])) and dt.date() == today]
    week_records = [h for h in valid if (dt := _parse_ran_at_kst(h["ran_at"])) and dt.date() >= week_start]

    def _sum(recs):
        return sum(h["voted"] for h in recs)

    def _avg(recs):
        return _sum(recs) / len(recs) if recs else 0

    total_voted = _sum(valid)
    total_skipped = sum(h["skipped"] for h in valid)

    known = [h for h in valid if h.get("is_full_scan") is not None]
    best_pool = known if known else valid
    best = max(best_pool, key=lambda h: h["voted"])
    worst = min(best_pool, key=lambda h: h["voted"])

    def _short_date(h):
        dt = _parse_ran_at_kst(h["ran_at"])
        return dt.strftime("%m/%d %H:%M") if dt else h["ran_at"][:16]

    if len(valid) >= 10:
        r5 = _avg(valid[-5:])
        p5 = _avg(valid[-10:-5])
        diff = r5 - p5
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "─")
        trend_str = f"{arrow} {abs(diff):.1f}  (최근5 평균 {r5:.1f}  /  이전5 평균 {p5:.1f})"
    else:
        trend_str = "데이터 부족 (10회 이상 필요)"

    full_scan = [h for h in valid if h.get("is_full_scan") is True]
    partial_scan = [h for h in valid if h.get("is_full_scan") is False]
    unknown_scan = [h for h in valid if h.get("is_full_scan") is None]
    scan_lines = ""
    if full_scan:
        scan_lines += f"  풀 스캔: 평균 {_avg(full_scan):.1f}개 ({len(full_scan)}회)\n"
    if partial_scan:
        scan_lines += f"  부분 스캔: 평균 {_avg(partial_scan):.1f}개 ({len(partial_scan)}회)\n"
    if unknown_scan:
        scan_lines += f"  알 수 없음: {len(unknown_scan)}회 (기존 레코드)\n"

    slots = {"심야(00~06)": [], "오전(06~12)": [], "오후(12~18)": [], "저녁(18~24)": []}
    for h in valid:
        dt = _parse_ran_at_kst(h["ran_at"])
        if dt is None:
            continue
        hr = dt.hour
        if hr < 6:
            slots["심야(00~06)"].append(h["voted"])
        elif hr < 12:
            slots["오전(06~12)"].append(h["voted"])
        elif hr < 18:
            slots["오후(12~18)"].append(h["voted"])
        else:
            slots["저녁(18~24)"].append(h["voted"])

    slot_avgs = {k: (sum(v) / len(v) if v else None) for k, v in slots.items()}
    best_slot = max(
        (k for k, v in slot_avgs.items() if v is not None),
        key=lambda k: slot_avgs[k],
        default=None,
    )
    time_lines = ""
    for k, v in slot_avgs.items():
        if v is None:
            time_lines += f"  {k}: -\n"
        else:
            star = " ★" if k == best_slot else ""
            time_lines += f"  {k}: 평균 {v:.1f}개 ({len(slots[k])}회){star}\n"

    recent_lines = ""
    show = history[-10:]
    for i, h in enumerate(show):
        idx = len(history) - len(show) + i + 1
        mark = "✗ " if not h.get("is_valid", True) else ""
        dt = _parse_ran_at_kst(h["ran_at"])
        dt_str = dt.strftime("%m/%d %H:%M") if dt else h["ran_at"][:16]
        board = h.get("board_name") or h.get("board_id", "")
        recent_lines += f"  {idx}. {mark}{dt_str}  {h['voted']}개  ({board})\n"

    sample_warn = "\n⚠️ 표본 부족 (참고용)" if len(valid) < 50 else ""

    return (
        f"📊 공감 통계{sample_warn}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"오늘: {_sum(today_records)}개 ({len(today_records)}회) | "
        f"이번주: {_sum(week_records)}개 ({len(week_records)}회)\n"
        f"전체: {total_voted}개 ({len(valid)}회) | 평균: {_avg(valid):.1f}개/회\n"
        f"건너뜀: {total_skipped}개\n"
        f"\n📈 추세\n  {trend_str}\n"
        f"\n🔍 스캔 유형별 평균\n{scan_lines}"
        f"\n🏆 최고: {best['voted']}개 ({_short_date(best)})  "
        f"최저: {worst['voted']}개 ({_short_date(worst)})\n"
        f"\n🕐 시간대별 패턴\n{time_lines}"
        f"\n📋 최근 기록 (번호로 /togglestat 사용)\n{recent_lines}"
    )


async def _do_togglestat(update: Update, idx: int) -> None:
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


async def _do_deletestat(update: Update, idx: int) -> None:
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


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    history = load_run_history()
    if not history:
        await update.message.reply_text("아직 실행 기록이 없습니다.")
        return
    await update.message.reply_text(_format_stats_message(history))


async def cmd_togglestat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    if context.args:
        try:
            idx = int(context.args[0]) - 1
        except ValueError:
            await update.message.reply_text("❌ 숫자를 입력해주세요.")
            return ConversationHandler.END
        await _do_togglestat(update, idx)
        return ConversationHandler.END
    await update.message.reply_text("토글할 레코드 번호를 입력해주세요:\n(/cancel 로 취소)")
    return ASK_TOGGLE_IDX


async def cmd_deletestat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return ConversationHandler.END
    if context.args:
        try:
            idx = int(context.args[0]) - 1
        except ValueError:
            await update.message.reply_text("❌ 숫자를 입력해주세요.")
            return ConversationHandler.END
        await _do_deletestat(update, idx)
        return ConversationHandler.END
    await update.message.reply_text("삭제할 레코드 번호를 입력해주세요:\n(/cancel 로 취소)")
    return ASK_DELETE_IDX


async def togglestat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(update.message.text.strip()) - 1
    except ValueError:
        await update.message.reply_text("❌ 숫자를 입력해주세요.")
        return ASK_TOGGLE_IDX
    await _do_togglestat(update, idx)
    return ConversationHandler.END


async def deletestat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(update.message.text.strip()) - 1
    except ValueError:
        await update.message.reply_text("❌ 숫자를 입력해주세요.")
        return ASK_DELETE_IDX
    await _do_deletestat(update, idx)
    return ConversationHandler.END


async def stat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("취소되었습니다.")
    return ConversationHandler.END
