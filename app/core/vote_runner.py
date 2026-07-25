import logging
import random
import time

from .clients.everytime import EverytimeClient
from .database import db
from ..config import PAGE_NUM, BOARD_PAGE_SIZE


def run_vote(
    *,
    client,
    storage,
    cfg,
    target_board: str,
    progress_callback=None,
    skip_keywords: list[str] | None = None,
) -> dict:
    processed = 0
    skipped = 0
    already = 0
    failed = 0
    final_page = 0
    scanned = 0
    scan_limit_reached = False
    checkpoint_found = False

    if not client.check_session(target_board):
        logging.error("세션이 유효하지 않아 종료합니다.")
        return {
            "processed": 0, "skipped": 0, "already": 0, "failed": 0,
            "candidates": 0, "scanned": 0, "final_page": 0,
            "checkpoint_found": False, "scan_limit_reached": False,
            "success": False,
        }

    checkpoint_id = storage.load("last_article_id")
    is_initial = checkpoint_id is None
    articles_to_vote = []
    first_article_id = None
    max_pages = cfg["bot"]["max_pages"]

    if is_initial:
        for i in range(max_pages):
            final_page = i + 1
            logging.info(f"[초기] {final_page}페이지 스캔 중...")
            page_articles = client.get_article_ids(target_board, start_num=i * 20)
            if not page_articles:
                break
            scanned += len(page_articles)
            if first_article_id is None:
                first_article_id = page_articles[0]["id"]
            articles_to_vote.extend(page_articles)
            time.sleep(cfg["timing"]["page_delay"])
        scan_limit_reached = final_page >= max_pages
    else:
        _, found_idx = client.find_article(
            target_board,
            checkpoint_id,
            max_pages=max_pages,
            page_delay=cfg["timing"]["page_delay"],
        )

        if found_idx == -1:
            logging.warning("체크포인트 게시글을 찾지 못했습니다 (게시글 삭제 추정). 스캔된 범위만 처리합니다.")
            checkpoint_found = False
            for i in range(max_pages):
                final_page = i + 1
                page_articles = client.get_article_ids(target_board, start_num=i * 20)
                if not page_articles:
                    break
                scanned += len(page_articles)
                if first_article_id is None:
                    first_article_id = page_articles[0]["id"]
                articles_to_vote.extend(page_articles)
                time.sleep(cfg["timing"]["page_delay"])
            scan_limit_reached = final_page >= max_pages
        else:
            checkpoint_found = True
            offset = 0
            found = False
            while not found:
                final_page += 1
                logging.info(f"[재개] {final_page}페이지 탐색 중 (체크포인트: {checkpoint_id})...")
                page_articles = client.get_article_ids(target_board, start_num=offset)
                if not page_articles:
                    break
                scanned += len(page_articles)
                if first_article_id is None:
                    first_article_id = page_articles[0]["id"]
                for article in page_articles:
                    if article["id"] == checkpoint_id:
                        found = True
                        break
                    articles_to_vote.append(article)
                if not found:
                    offset += 20
                    time.sleep(cfg["timing"]["page_delay"])
            scan_limit_reached = False

    for item in articles_to_vote:
        title = (item.get("title") or "").lower()
        if skip_keywords and any(kw.lower() in title for kw in skip_keywords):
            logging.info(f"[{item['id']}] 건너뜀 (키워드 일치): {item.get('title')}")
            skipped += 1
            continue

        if item.get("posvote", 0) >= 1:
            logging.info(f"[{item['id']}] 건너뜀 (공감 {item['posvote']}개): {item.get('title')}")
            skipped += 1
            continue

        vote_result = client.push_vote(article_id=item["id"])
        if vote_result == "voted":
            processed += 1
        elif vote_result == "already":
            already += 1
        else:
            failed += 1
        if progress_callback:
            progress_callback(processed, final_page)
        time.sleep(random.uniform(
            cfg["timing"]["sleep_min"],
            cfg["timing"]["sleep_max"],
        ))

    if first_article_id and failed == 0:
        storage.save("last_article_id", first_article_id)
    elif failed:
        logging.warning("실패한 투표가 있어 체크포인트를 갱신하지 않습니다.")

    return {
        "processed": processed,
        "skipped": skipped,
        "already": already,
        "failed": failed,
        "candidates": len(articles_to_vote),
        "scanned": scanned,
        "final_page": final_page,
        "checkpoint_found": checkpoint_found,
        "scan_limit_reached": scan_limit_reached,
        "is_initial": is_initial,
        "success": True,
    }


class VoteRunner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.storage = db
        self.supabase = self.storage.supabase

        session_value = self.storage.load("etsid")
        if not session_value:
            raise ValueError("etsid가 저장되어 있지 않습니다. /setsession 을 먼저 실행하세요.")

        self.client = EverytimeClient(session_value)
        saved_board = self.storage.load("board_id")
        self.target_board = saved_board if saved_board else cfg["bot"]["board_id"]

    def check_session(self, board_id):
        return self.client.check_session(board_id)

    def get_board_list(self) -> list[dict]:
        return self.client.get_board_list()

    def delete_my_articles(self) -> int:
        """최신 페이지에서 본인(is_mine=True) 게시글을 찾아 삭제. 삭제된 개수 반환."""
        deleted = 0
        for page_idx in range(BOARD_PAGE_SIZE):
            articles = self.client.get_article_ids(self.target_board, start_num=page_idx*PAGE_NUM)
            for a in articles:
                if a.get("is_mine"):
                    if not a.get("posvote"):
                        if self.client.delete_article(a["id"]):
                            deleted += 1
        return deleted

    def start(self, progress_callback=None, skip_keywords: list[str] | None = None) -> dict:
        return run_vote(
            client=self.client,
            storage=self.storage,
            cfg=self.cfg,
            target_board=self.target_board,
            progress_callback=progress_callback,
            skip_keywords=skip_keywords,
        )
