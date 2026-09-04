"""취향 파라미터와 LLM이 측정한 게시글 특성을 조합해 최종 점수/결정을 계산한다.

LLM은 게시글의 특성만 측정하고, "좋아요를 누를지"는 이 모듈이 코드로 계산한다.
과도하게 복잡한 수학 모델은 쓰지 않는다 (가중 평균 + 간단한 strictness 커브 + 좁은 exploration 구간).
"""

import random

# threshold 바로 아래 exploration 구간에 들어온 글 중 실제로 뽑힐 확률.
# exploration(설정값)은 구간의 폭만 정하고, 뽑힐 확률은 아래 상수로 고정한다
# (하나의 값에 두 가지 의미를 섞지 않기 위함).
EXPLORATION_PICK_PROBABILITY = 0.3
# penalty_score가 이 값 이상이면 exploration 대상에서 제외한다.
EXPLORATION_MAX_PENALTY = 0.4


def _weighted_average(features: dict, weights: dict) -> float:
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0
    total = sum(features.get(name, 0.0) * weight for name, weight in weights.items())
    return total / total_weight


def calculate_positive_score(features: dict, preferences: dict) -> float:
    return _weighted_average(features, preferences)


def calculate_penalty_score(features: dict, penalties: dict) -> float:
    return _weighted_average(features, penalties)


def calculate_final_score(positive_score: float, penalty_score: float, penalty_strength: float) -> float:
    base_score = positive_score - penalty_score * penalty_strength
    return max(0.0, min(1.0, base_score))


def apply_strictness(score: float, strictness: float) -> float:
    """strictness가 높을수록 중간 점수를 threshold 아래로 더 밀어낸다.

    score ** (1 + strictness): score=1.0은 항상 1.0에 가깝게 유지되지만
    score=0.7처럼 애매한 값은 strictness가 높을수록 더 낮게 눌린다.
    """
    strictness = max(0.0, min(1.0, strictness))
    return max(0.0, min(1.0, score)) ** (1 + strictness)


def calculate_score(features: dict, taste_cfg: dict) -> dict:
    """positive/penalty/final/adjusted 점수를 한 번에 계산한다."""
    preferences = taste_cfg.get("preferences", {})
    penalties = taste_cfg.get("penalties", {})
    decision_cfg = taste_cfg.get("decision", {})

    positive_score = calculate_positive_score(features, preferences)
    penalty_score = calculate_penalty_score(features, penalties)
    final_score = calculate_final_score(
        positive_score, penalty_score, decision_cfg.get("penalty_strength", 1.0)
    )
    adjusted_score = apply_strictness(final_score, decision_cfg.get("strictness", 0.0))

    return {
        "positive_score": positive_score,
        "penalty_score": penalty_score,
        "final_score": final_score,
        "adjusted_score": adjusted_score,
    }


def apply_hard_reject(features: dict, hard_reject_cfg: dict | None) -> str | None:
    """features 중 하나라도 hard_reject 임계값 이상이면 해당 항목명을 반환한다 (optional 기능)."""
    if not hard_reject_cfg:
        return None
    for name, cutoff in hard_reject_cfg.items():
        if features.get(name, 0.0) >= cutoff:
            return name
    return None


def make_decision(
    score_result: dict,
    confidence: float,
    taste_cfg: dict,
    *,
    hard_reject_reason: str | None = None,
    rng=random,
) -> tuple[str, str]:
    """("LIKE" | "SKIP" | "REJECT", 이유 문자열)을 반환한다."""
    decision_cfg = taste_cfg.get("decision", {})
    threshold = decision_cfg.get("threshold", 0.68)
    exploration = decision_cfg.get("exploration", 0.0)
    min_confidence = decision_cfg.get("min_confidence", 0.45)
    adjusted_score = score_result["adjusted_score"]
    penalty_score = score_result["penalty_score"]

    if hard_reject_reason:
        return "REJECT", f"hard_reject:{hard_reject_reason}"

    if confidence < min_confidence:
        return "SKIP", f"low_confidence:{confidence:.2f}<{min_confidence:.2f}"

    if adjusted_score >= threshold:
        return "LIKE", f"score {adjusted_score:.3f} >= threshold {threshold:.3f}"

    band_low = threshold - exploration
    if band_low <= adjusted_score < threshold and penalty_score < EXPLORATION_MAX_PENALTY:
        if rng.random() < EXPLORATION_PICK_PROBABILITY:
            return "LIKE", f"exploration pick (score {adjusted_score:.3f} in [{band_low:.3f}, {threshold:.3f}))"

    return "SKIP", f"score {adjusted_score:.3f} < threshold {threshold:.3f}"


def compute_contributions(features: dict, weights: dict) -> dict[str, float]:
    """로그용: 각 항목이 가중 평균에 실제로 기여한 양(feature * weight / sum_weight)."""
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {}
    return {
        name: features.get(name, 0.0) * weight / total_weight
        for name, weight in weights.items()
    }
