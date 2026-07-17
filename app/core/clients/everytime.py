import logging
import time
from typing import Literal
from xml.etree import ElementTree

import requests


class EverytimeClient:
    BASE_URL = "https://api.everytime.kr"

    def __init__(self, etsid: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Host": "api.everytime.kr",
            "Connection": "keep-alive",
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://everytime.kr",
            "Referer": "https://everytime.kr/",
            "Cookie": f"etsid={etsid};",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
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
            "id": board_id,
            "limit_num": 1,
            "start_num": 0,
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
        self.session.headers["Referer"] = f"https://everytime.kr/{board_id}"
        res_text = self._post(
            "/find/board/article/list",
            data={"id": board_id, "limit_num": limit_num, "start_num": start_num},
        )
        if res_text == "0" or "<response>0</response>" in res_text:
            logging.error("세션 만료 또는 권한 부족")
            return []
        try:
            root = ElementTree.fromstring(res_text)
            return [
                {
                    "id": a.get("id"),
                    "title": a.get("title", ""),
                    "created_at": a.get("created_at", ""),
                    "posvote": int(a.get("posvote", "0") or "0"),
                }
                for a in root.findall(".//article")
            ]
        except Exception as e:
            logging.error(f"파싱 에러: {e}")
            return []

    def find_article(self, board_id, before_article_id, max_pages=50, page_delay=0.5):
        count = 0
        offset = 0
        for _ in range(max_pages):
            articles = self.get_article_ids(board_id, start_num=offset)
            for item in articles:
                if item["id"] == before_article_id:
                    return count, articles.index(item)
                count += 1
            offset += 20
            time.sleep(page_delay)
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

    def delete_article(self, article_id) -> bool:
        """자유게시판 본인 게시글 삭제. 응답 포맷은 실제 호출 후 확인해서 아래 분기 수정할 것."""
        data = {"id": article_id}
        try:
            res_text = self._post("/remove/board/article", data=data).strip()
            logging.info(f"[삭제 응답 원문] {res_text}")  # 최초 실행 시 이 로그로 포맷 확인
            if res_text == "1" or "<response>1</response>" in res_text:
                logging.info(f"[{article_id}] 삭제 완료")
                return True
            logging.warning(f"[{article_id}] 삭제 실패 응답: {res_text}")
            return False
        except Exception as e:
            logging.error(f"에러 발생: {e}")
            return False

    def get_unread_count(self) -> int | None:
        """메시지함 안읽음 개수 조회. 활동 감지용 신호로 사용."""
        try:
            res_text = self._post("/find/messageBox/unreadCount", data={}).strip()
            logging.info(f"[unreadCount 응답 원문] {res_text}")  # 최초 실행 시 포맷 확인
            # TODO: 실제 응답 구조 확인 후 파싱 로직 작성 (숫자 그대로 오는지, XML인지)
            return int(res_text) if res_text.isdigit() else None
        except Exception as e:
            logging.error(f"unreadCount 조회 에러: {e}")
            return None

    def push_vote(self, article_id) -> Literal["voted", "already", "failed"]:
        data = {"id": article_id, "vote": "1"}
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
