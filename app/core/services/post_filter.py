"""LLM 호출 전에 명확히 제외할 수 있는 게시글을 걸러낸다 (API 비용 절감용)."""

MIN_CONTENT_LENGTH = 2


def hard_filter(article: dict, *, skip_keywords: list[str] | None = None) -> str | None:
    """통과하면 None, 제외해야 하면 사유 문자열을 반환한다."""
    title = (article.get("title") or "").strip()
    content = (article.get("content") or "").strip()

    if not title and not content:
        return "empty_content"

    if len(title) + len(content) < MIN_CONTENT_LENGTH:
        return "empty_content"

    if skip_keywords:
        haystack = title.lower()
        for kw in skip_keywords:
            if kw.lower() in haystack:
                return f"blacklist_keyword:{kw}"

    return None
