import os
import sys
import time
import random
import logging
import argparse

import requests
import yaml
from dotenv import load_dotenv
from xml.etree import ElementTree

"""
첫 번째 실행: 세션키 얻음 -> 요청 날림 -> 처음에 200개 세팅 후 클릭 -> 게시글 아이디 저장
두 번째 실행: 세션키 얻음 -> 게시글 찾기 -> 요청 날림 ->
"""

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
    "state": {
        "last_article_file": "last_article.txt",
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


def load_config(path="config.yaml"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        user_cfg = {}
    return _deep_merge(DEFAULTS, user_cfg)


class EverytimeBot:
    BASE_URL = "https://api.everytime.kr"

    def __init__(self, cfg):
        from storage import SecureStorage
        self.cfg = cfg
        self.storage = SecureStorage()
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
            print(f"[ERROR] {e}")
            logging.error(f"[ERROR] {e}")
            return ""

    def check_session(self, board_id):
        print(f"[DEBUG] board_id: {board_id}")
        print(f"[DEBUG] cookie: {self.session.headers.get('Cookie')}")
    
        res_text = self._post("/find/board/article/list", data={
            'id': board_id,
            'limit_num': 1,
            'start_num': 0
        })
        if "<response>" in res_text:
            print("세션 유효: 로그인 성공 상태입니다.")
            logging.info("세션 유효: 로그인 성공 상태입니다.")
            return True
        else:
            print(f"세션 무효: {res_text}")
            logging.error(f"세션 무효: {res_text}")
            return False

    def get_article_ids(self, board_id, limit_num=20, start_num=0):
        self.session.headers['Referer'] = f'https://everytime.kr/{board_id}'
        res_text = self._post(
            "/find/board/article/list",
            data={
                'id': board_id,
                'limit_num': limit_num,
                'start_num': start_num
            }
        )
        if res_text == "0" or "<response>0</response>" in res_text:
            print("결과: 세션이 만료되었거나 학교 인증 권한이 부족합니다.")
            logging.error("결과: 세션이 만료되었거나 학교 인증 권한이 부족합니다.")
            return []
        try:
            root = ElementTree.fromstring(res_text)
            articles = [
                {"id": article.get('id'), "title": article.get('title', '')}
                for article in root.findall('.//article')
            ]
            return articles
        except Exception as e:
            print(f"파싱 에러: {e}")
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
        print(f"게시글({before_article_id})을 찾을 수 없습니다.")
        return count, -1

    def push_vote(self, article_id):
        data = {'id': article_id, 'vote': '1'}
        try:
            res_text = self._post("/save/board/article/vote", data=data)
            if "1" in res_text:
                print(f"[{article_id}] 공감 완료!")
                logging.info(f"[{article_id}] 공감 완료!")
                return True
            elif "-1" in res_text:
                print(f"[{article_id}] 이미 공감한 글입니다.")
                logging.info(f"[{article_id}] 이미 공감한 글입니다.")
                return True
            else:
                print(f"[{article_id}] 실패 응답: {res_text}")
                logging.warning(f"[{article_id}] 실패 응답: {res_text}")
                return False
        except Exception as e:
            print(f"에러 발생: {e}")
            logging.error(f"에러 발생: {e}")
            return False


class Main(EverytimeBot):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.target_board = cfg["bot"]["board_id"]
        self.last_article_file = cfg["state"]["last_article_file"]
        self.id_title_map: dict[str, str] = {}

    def save_last_id(self, article_id):
        with open(self.last_article_file, 'w', encoding='utf-8') as f:
            f.write(str(article_id))

    def read_last_id(self):
        try:
            with open(self.last_article_file, 'r', encoding='utf-8') as f:
                return f.readline().strip()
        except FileNotFoundError:
            return None

    def start(self) -> dict:
        max_pages = self.cfg["bot"]["max_pages"]
        processed = 0

        if not self.check_session(self.target_board):
            logging.error("세션이 유효하지 않아 종료합니다.")
            return {"processed": 0, "last_id": None, "success": False}

        last_id = self.read_last_id()
        logging.info(f"마지막 작업 게시글 ID: {last_id}")

        new_latest_id = None

        for i in range(max_pages):
            start_index = i * 20
            logging.info(f"현재 {i+1}페이지(시작 인덱스: {start_index}) 분석 중...")

            current_ids = self.get_article_ids(self.target_board, start_num=start_index)

            if not current_ids:
                break

            if i == 0 and current_ids:
                new_latest_id = current_ids[0]

            for article_id in current_ids:
                if str(article_id) == str(last_id):
                    logging.info("이전 작업 지점에 도달했습니다. 종료합니다.")
                    if new_latest_id:
                        self.save_last_id(new_latest_id)
                    return {"processed": processed, "last_id": new_latest_id, "success": True}

                self.push_vote(article_id=article_id)
                processed += 1
                time.sleep(random.uniform(
                    self.cfg["timing"]["sleep_min"],
                    self.cfg["timing"]["sleep_max"],
                ))

        if new_latest_id:
            self.save_last_id(new_latest_id)

        return {"processed": processed, "last_id": new_latest_id, "success": True}


if __name__ == "__main__":
    load_dotenv()

    parser = argparse.ArgumentParser(description='Everytime Auto Vote Bot')
    parser.add_argument('--board', type=str, default=None, help='Target Board ID (overrides config)')
    parser.add_argument('--pages', type=int, default=None, help='Max pages to scan (overrides config)')
    args = parser.parse_args()

    cfg = load_config()
    if args.board is not None:
        cfg["bot"]["board_id"] = args.board
    if args.pages is not None:
        cfg["bot"]["max_pages"] = args.pages

    logging.basicConfig(
        level=getattr(logging, cfg["logging"]["level"].upper(), logging.INFO),
        format=cfg["logging"]["format"],
    )

    bot = Main(cfg)
    result = bot.start()
    print(result)
