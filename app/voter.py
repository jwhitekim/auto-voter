import time
import random
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
        if "<response>" in res_text:
            logging.info("세션 유효: 로그인 성공 상태입니다.")
            return True
        else:
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
                {"id": a.get('id'), "title": a.get('title', ''), "created_at": a.get('created_at', '')}
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

    def push_vote(self, article_id):
        data = {'id': article_id, 'vote': '1'}
        try:
            res_text = self._post("/save/board/article/vote", data=data)
            if "1" in res_text:
                logging.info(f"[{article_id}] 공감 완료!")
                return True
            elif "-1" in res_text:
                logging.info(f"[{article_id}] 이미 공감한 글입니다.")
                return True
            else:
                logging.warning(f"[{article_id}] 실패 응답: {res_text}")
                return False
        except Exception as e:
            logging.error(f"에러 발생: {e}")
            return False


class Main(EverytimeBot):
    def __init__(self, cfg):
        super().__init__(cfg)
        saved_board = self.storage.load("board_id")
        self.target_board = saved_board if saved_board else cfg["bot"]["board_id"]
        self.id_title_map: dict[str, str] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _now_kst(self) -> str:
        return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")

    def save_checkpoint(self, post_id: str, post_title: str = "", post_created_at: str = "", voted_at: str = "") -> None:
        now = self._now()
        entries = [
            ("last_article_id",         str(post_id)),
            ("last_article_title",      post_title),
            ("last_article_created_at", post_created_at),
            ("last_voted_at",           voted_at or self._now_kst()),
            ("last_board_id",           self.target_board),
        ]
        try:
            for key, value in entries:
                self.supabase.table("bot_state").upsert(
                    {"key": key, "value": value, "updated_at": now}
                ).execute()
        except Exception as e:
            logging.error(f"save_checkpoint 실패: {e}")

    def read_checkpoint(self) -> dict:
        empty = {"post_id": None, "post_title": "", "post_created_at": "", "voted_at": ""}
        keys = ["last_article_id", "last_article_title", "last_article_created_at", "last_voted_at", "last_board_id"]
        key_map = {
            "last_article_id":         "post_id",
            "last_article_title":      "post_title",
            "last_article_created_at": "post_created_at",
            "last_voted_at":           "voted_at",
        }
        try:
            res = (
                self.supabase.table("bot_state")
                .select("key,value")
                .in_("key", keys)
                .execute()
            )
            rows = {row["key"]: row["value"] for row in (res.data or [])}
            if rows.get("last_board_id") != self.target_board:
                logging.info(f"게시판 변경 감지 ({rows.get('last_board_id')} → {self.target_board}), 체크포인트 초기화")
                return empty
            out = empty.copy()
            for key, field in key_map.items():
                if key in rows:
                    out[field] = rows[key]
            return out
        except Exception as e:
            logging.error(f"read_checkpoint 실패: {e}")
        return empty

    def start(self, progress_callback=None, skip_keywords: list[str] | None = None) -> dict:
        max_pages = self.cfg["bot"]["max_pages"]
        processed = 0
        skipped = 0
        new_latest_id = None
        new_latest_title = None
        new_latest_created_at = None
        final_page = 0

        if not self.check_session(self.target_board):
            logging.error("세션이 유효하지 않아 종료합니다.")
            return {"processed": 0, "skipped": 0, "last_id": None, "last_title": None, "last_created_at": None, "final_page": 0, "success": False}

        checkpoint = self.read_checkpoint()
        last_id = checkpoint["post_id"]
        last_created_at = checkpoint["post_created_at"]
        logging.info(f"마지막 작업 게시글 ID: {last_id}, created_at: {last_created_at}")

        def _ts(s):
            try:
                return int(s)
            except (ValueError, TypeError):
                return 0

        last_ts = _ts(last_created_at)

        for i in range(max_pages):
            start_index = i * 20
            final_page = i + 1
            logging.info(f"현재 {i+1}페이지(시작 인덱스: {start_index}) 분석 중...")

            articles = self.get_article_ids(self.target_board, start_num=start_index)
            if not articles:
                break

            if i == 0:
                new_latest_id = articles[0]['id']
                new_latest_title = articles[0]['title']
                new_latest_created_at = articles[0].get('created_at', '')

            for item in articles:
                self.id_title_map[item['id']] = item['title']

                if str(item['id']) == str(last_id):
                    logging.info("이전 작업 지점에 도달했습니다. 종료합니다.")
                    if new_latest_id:
                        self.save_checkpoint(new_latest_id, new_latest_title or "", new_latest_created_at or "")
                    return {
                        "processed": processed,
                        "skipped": skipped,
                        "last_id": new_latest_id,
                        "last_title": new_latest_title,
                        "last_created_at": new_latest_created_at,
                        "final_page": final_page,
                        "success": True,
                        "is_full_scan": last_id is None,
                    }

                # 체크포인트 게시글이 삭제된 경우: 저장된 타임스탬프보다 오래된 글에 도달하면 중단
                if last_ts and _ts(item.get('created_at', '')) <= last_ts:
                    logging.warning(
                        f"체크포인트({last_id})를 찾지 못했으나 타임스탬프 기준 도달. "
                        f"삭제된 게시글로 판단하고 중단합니다. (처리: {processed}개)"
                    )
                    if new_latest_id:
                        self.save_checkpoint(new_latest_id, new_latest_title or "", new_latest_created_at or "")
                    return {
                        "processed": processed,
                        "skipped": skipped,
                        "last_id": new_latest_id,
                        "last_title": new_latest_title,
                        "last_created_at": new_latest_created_at,
                        "final_page": final_page,
                        "success": True,
                        "is_full_scan": last_id is None,
                    }

                title = (item.get('title') or '').lower()
                if skip_keywords and any(kw.lower() in title for kw in skip_keywords):
                    logging.info(f"[{item['id']}] 건너뜀 (키워드 일치): {item.get('title')}")
                    skipped += 1
                    continue

                self.push_vote(article_id=item['id'])
                processed += 1
                if progress_callback:
                    progress_callback(processed, final_page)
                time.sleep(random.uniform(
                    self.cfg["timing"]["sleep_min"],
                    self.cfg["timing"]["sleep_max"],
                ))

        if new_latest_id:
            self.save_checkpoint(new_latest_id, new_latest_title or "", new_latest_created_at or "")

        return {
            "processed": processed,
            "skipped": skipped,
            "last_id": new_latest_id,
            "last_title": new_latest_title,
            "last_created_at": new_latest_created_at,
            "final_page": final_page,
            "success": True,
            "is_full_scan": last_id is None,
        }
