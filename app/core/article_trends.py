import math
from datetime import datetime

from ..config import KST


def parse_article_datetime(value: str) -> datetime | None:
    """Everytime 게시글 시각을 timezone-aware datetime으로 변환한다."""
    if not value:
        return None

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _minutes(value: tuple[int, int]) -> int:
    return value[0] * 60 + value[1]


def _as_time(value: int) -> tuple[int, int]:
    return divmod(value, 60)


def _best_window(
    samples: list[tuple[datetime, float]],
    search_range,
    duration_minutes: int,
    step_minutes: int,
    fallback,
    minimum_slot_samples: int,
):
    range_start = _minutes(search_range[0])
    range_end = _minutes(search_range[1])
    fallback_start = _minutes(fallback[0])
    best = None

    for start in range(range_start, range_end - duration_minutes + 1, step_minutes):
        end = start + duration_minutes
        matching = [
            weight
            for created_at, weight in samples
            if start <= created_at.hour * 60 + created_at.minute < end
        ]
        candidate = (
            sum(matching),
            len(matching),
            -abs(start - fallback_start),
            -start,
            start,
        )
        if best is None or candidate > best:
            best = candidate

    if best is None or best[1] < minimum_slot_samples:
        return fallback, 0

    start = best[-1]
    return (_as_time(start), _as_time(start + duration_minutes)), best[1]


def infer_activity_windows(
    articles: list[dict],
    *,
    now: datetime,
    fallback_windows,
    search_ranges,
    lookback_days: int,
    minimum_samples: int,
    minimum_slot_samples: int,
    duration_minutes: int = 180,
    step_minutes: int = 30,
) -> tuple[list, dict]:
    """
    최근 게시 시각 분포에서 각 슬롯의 활동 밀도가 가장 높은 구간을 찾는다.

    최신 게시글일수록 더 크게 반영하고, 추천 수는 상한이 있는 약한 가중치로
    사용한다. 표본이 부족하면 모든 슬롯을 기존 시간대로 유지한다.
    """
    localized_now = now.astimezone(KST)
    samples: list[tuple[datetime, float]] = []

    for article in articles:
        created_at = parse_article_datetime(article.get("created_at", ""))
        if created_at is None:
            continue
        age_days = (localized_now - created_at).total_seconds() / 86_400
        if age_days < 0 or age_days > lookback_days:
            continue

        recency_weight = 0.5 ** (age_days / max(lookback_days / 2, 1))
        votes = max(int(article.get("posvote", 0) or 0), 0)
        engagement_weight = 1 + min(math.log1p(votes) * 0.15, 0.5)
        samples.append((created_at, recency_weight * engagement_weight))

    summary = {
        "sample_count": len(samples),
        "lookback_days": lookback_days,
        "slot_sample_counts": [0] * len(fallback_windows),
        "used_fallback": False,
    }
    if len(samples) < minimum_samples:
        summary["used_fallback"] = True
        summary["selected_windows"] = list(fallback_windows)
        return list(fallback_windows), summary

    windows = []
    for search_range, fallback in zip(search_ranges, fallback_windows):
        window, sample_count = _best_window(
            samples,
            search_range,
            duration_minutes,
            step_minutes,
            fallback,
            minimum_slot_samples,
        )
        windows.append(window)
        summary["slot_sample_counts"][len(windows) - 1] = sample_count

    summary["used_fallback"] = windows == list(fallback_windows)
    summary["selected_windows"] = windows
    return windows, summary
