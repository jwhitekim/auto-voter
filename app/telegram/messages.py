def format_vote_result(result: dict, now_str: str) -> str:
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

    if is_initial:
        scan_line = f"🔎 초기 스캔: {page}페이지, 게시글 {scanned}개"
    elif checkpoint_found:
        scan_line = f"🔎 지난 실행 이후 새 글 {candidates}개 발견 (체크포인트까지 {page}페이지 탐색)"
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

    return (
        f"{status}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{scan_line}\n"
        + "\n".join(result_lines) +
        f"\n🕐 {now_str}\n"
        f"{checkpoint_line}"
    )
