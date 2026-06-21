from ..clients.everytime import EverytimeClient
from ..storage import SecureStorage
from .voting import run_vote


class VoteRunner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.storage = SecureStorage()
        self.supabase = self.storage.supabase

        session_value = self.storage.load("etsid")
        if not session_value:
            raise ValueError("etsid가 저장되어 있지 않습니다. /login 을 먼저 실행하세요.")

        self.client = EverytimeClient(session_value)
        saved_board = self.storage.load("board_id")
        self.target_board = saved_board if saved_board else cfg["bot"]["board_id"]

    def check_session(self, board_id):
        return self.client.check_session(board_id)

    def get_board_list(self) -> list[dict]:
        return self.client.get_board_list()

    def start(self, progress_callback=None, skip_keywords: list[str] | None = None) -> dict:
        return run_vote(
            client=self.client,
            storage=self.storage,
            cfg=self.cfg,
            target_board=self.target_board,
            progress_callback=progress_callback,
            skip_keywords=skip_keywords,
        )
