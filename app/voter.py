import time
import random
import logging
from pathlib import Path
from typing import Literal

import requests
import yaml
from dotenv import load_dotenv
from xml.etree import ElementTree

DEFAULTS = {
    "bot": {
        "board_id": "389115",
        "max_pages": 5,
    },
    "timing": {
        "sleep_min": 1.0,
        "sleep_max": 3.0,
        "page_delay": 0.5,
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(levelname)s - %(message)s",
    },
}


def _deep_merge(base, override):
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


_ROOT = Path(__file__).parent.parent


def load_config(path=None):
    if path is None:
        path = _ROOT / "config" / "config.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        user_cfg = {}
    return _deep_merge(DEFAULTS, user_cfg)


class EverytimeBot:
    BASE_URL = "https://api.everytime.kr"

    def __init__(self, cfg):
        from .storage import SecureStorage
        self.cfg = cfg
        self.storage = SecureStorage()
        self.supabase = self.storage.supabase

        session_value = self.storage.load("etsid")
        if not session_value:
            raise ValueError("etsid가 저장되어 있지 않습니다. /login 을 먼저 실행하세요.")

        self.session = requests.Session()
        self.session.headers.update({
            'Host': 'api.everytime.kr',
            'Connection': 'keep-alive',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://everytime.kr',
            'Referer': 'https://everytime.kr/',
            'Cookie': f'etsid={session_value};',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })

    def _post(self, path, data=None):
        try:
            url = f"{self.BASE_URL}{path}"
            response = self.session.post(url, data=data, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.error(f"[ERROR] {e}")
            return ""

    def check_session(self, board_id):
        res_text = self._post("/find/board/article/list", data={
            'id': board_id,
            'limit_num': 1,
            'start_num': 0
        })
        stripped = res_text.strip()
        if stripped == "0" or "<response>0</response>" in stripped:
            logging.error(f"세션 무효: {res_text}")
            return False
        if "<response>" in stripped:
            logging.info("세션 유효: 로그인 성공 상태입니다.")
            return True
        logging.error(f"세션 무효: {res_text}")
        return False

    def get_article_ids(self, board_id, limit_num=20, start_num=0):
        self.session.headers['Referer'] = f'https://everytime.kr/{board_id}'
        res_text = self._post(
            "/find/board/article/list",
            data={'id': board_id, 'limit_num': limit_num, 'start_num': start_num}
        )
        if res_text == "0" or "<response>0</response>" in res_text:
            logging.error("세션 만료 또는 권한 부족")
            return []
        try:
            root = ElementTree.fromstring(res_text)
            return [
                {
                    "id": a.get('id'),
                    "title": a.get('title', ''),
                    "created_at": a.get('created_at', ''),
                    "posvote": int(a.get('posvote', '0') or '0'),
                }
                for a in root.findall('.//article')
            ]
        except Exception as e:
            logging.error(f"파싱 에러: {e}")
            return []

    def find_article(self, board_id, before_article_id, max_pages=50):
        count = 0
        offset = 0
        for _ in range(max_pages):
            articles = self.get_article_ids(board_id, start_num=offset)
            for item in articles:
                if item['id'] == before_article_id:
                    return count, articles.index(item)
                else:
                    count += 1
            offset += 20
            time.sleep(self.cfg["timing"]["page_delay"])
        return count, -1

    def get_board_list(self) -> list[dict]:
        res_text = self._post("/find/community/web", data={})
        if not res_text or "<response>" not in res_text:
            logging.error(f"게시판 목록 응답 오류: {res_text[:200] if res_text else 'empty'}")
            return []
        try:
            root = ElementTree.fromstring(res_text)
            boards = []
            for tag in ("board", "community"):
                for b in root.findall(f".//{tag}"):
                    bid = b.get("id")
                    name = b.get("name", "") or b.get("title", "")
                    if bid and name:
                        boards.append({"id": bid, "name": name})
            return boards
        except Exception as e:
            logging.error(f"게시판 목록 파싱 에러: {e}")
            return []

    def push_vote(self, article_id) -> Literal["voted", "already", "failed"]:
        data = {'id': article_id, 'vote': '1'}
        try:
            res_text = self._post("/save/board/article/vote", data=data).strip()
            if res_text == "-1" or "<response>-1</response>" in res_text:
                logging.info(f"[{article_id}] 이미 공감한 글입니다.")
                return "already"
            if res_text == "1" or "<response>1</response>" in res_text:
                logging.info(f"[{article_id}] 공감 완료!")
                return "voted"
            if "-1" in res_text:
                logging.info(f"[{article_id}] 이미 공감한 글입니다.")
                return "already"
            logging.warning(f"[{article_id}] 실패 응답: {res_text}")
            return "failed"
        except Exception as e:
            logging.error(f"에러 발생: {e}")
            return "failed"


class Main(EverytimeBot):
    def __init__(self, cfg):
        super().__init__(cfg)
        saved_board = self.storage.load("board_id")
        self.target_board = saved_board if saved_board else cfg["bot"]["board_id"]
        self.id_title_map: dict[str, str] = {}

    def start(self, progress_callback=None, skip_keywords: list[str] | None = None) -> dict:
        processed = 0
        skipped = 0
        already = 0
        failed = 0
        final_page = 0
        scanned = 0
        scan_limit_reached = False
        checkpoint_found = False

        if not self.check_session(self.target_board):
            logging.error("세션이 유효하지 않아 종료합니다.")
            return {
                "processed": 0, "skipped": 0, "already": 0, "failed": 0,
                "candidates": 0, "scanned": 0, "final_page": 0,
                "checkpoint_found": False, "scan_limit_reached": False,
                "success": False,
            }

        checkpoint_id = self.storage.load("last_article_id")
        is_initial = checkpoint_id is None
        articles_to_vote = []
        first_article_id = None  # 이번 실행의 최신 게시글 (새 체크포인트)

        if is_initial:
            max_pages = self.cfg["bot"]["max_pages"]
            for i in range(max_pages):
                final_page = i + 1
                logging.info(f"[초기] {final_page}페이지 스캔 중...")
                page_articles = self.get_article_ids(self.target_board, start_num=i * 20)
                if not page_articles:
                    break
                scanned += len(page_articles)
                if first_article_id is None:
                    first_article_id = page_articles[0]['id']
                articles_to_vote.extend(page_articles)
                time.sleep(self.cfg["timing"]["page_delay"])
            scan_limit_reached = final_page >= max_pages
        else:
            offset = 0
            found = False
            max_pages = self.cfg["bot"]["max_pages"]
            while not found and final_page < max_pages:
                final_page += 1
                logging.info(f"[재개] {final_page}페이지 탐색 중 (체크포인트: {checkpoint_id})...")
                page_articles = self.get_article_ids(self.target_board, start_num=offset)
                if not page_articles:
                    break
                scanned += len(page_articles)
                if first_article_id is None:
                    first_article_id = page_articles[0]['id']
                for article in page_articles:
                    if article['id'] == checkpoint_id:
                        found = True
                        break
                    articles_to_vote.append(article)
                if not found:
                    offset += 20
                    time.sleep(self.cfg["timing"]["page_delay"])
            checkpoint_found = found
            scan_limit_reached = not found and final_page >= max_pages
            if not found:
                logging.warning("체크포인트 게시글을 찾지 못했습니다. 스캔된 범위만 처리합니다.")

        for item in articles_to_vote:
            self.id_title_map[item['id']] = item['title']

            title = (item.get('title') or '').lower()
            if skip_keywords and any(kw.lower() in title for kw in skip_keywords):
                logging.info(f"[{item['id']}] 건너뜀 (키워드 일치): {item.get('title')}")
                skipped += 1
                continue

            if item.get('posvote', 0) >= 1:
                logging.info(f"[{item['id']}] 건너뜀 (공감 {item['posvote']}개): {item.get('title')}")
                skipped += 1
                continue

            vote_result = self.push_vote(article_id=item['id'])
            if vote_result == "voted":
                processed += 1
            elif vote_result == "already":
                already += 1
            else:
                failed += 1
            if progress_callback:
                progress_callback(processed, final_page)
            time.sleep(random.uniform(
                self.cfg["timing"]["sleep_min"],
                self.cfg["timing"]["sleep_max"],
            ))

        if first_article_id and failed == 0:
            self.storage.save("last_article_id", first_article_id)
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
