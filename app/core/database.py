import json
import logging
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from supabase import create_client

from ..config import get_encryption_key, get_supabase_credentials, load_env, set_encryption_key


class SecureDatabase:
    def __init__(self):
        load_env()

        url, key_sb = get_supabase_credentials()
        if not url or not key_sb:
            raise RuntimeError("SUPABASE_URL 또는 SUPABASE_KEY 환경변수가 설정되지 않았습니다.")

        self.supabase = create_client(url, key_sb)

        enc_key = get_encryption_key()
        if not enc_key:
            enc_key = Fernet.generate_key().decode()
            set_encryption_key(enc_key)
            logging.warning(
                "새 암호화 키를 생성했습니다. "
                "Railway 배포 시 ENCRYPTION_KEY를 영구 환경변수로 설정하세요."
            )
        self._fernet = Fernet(enc_key.encode())

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, encrypted: str) -> str | None:
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except Exception:
            logging.error("복호화 실패")
            return None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def save(self, key: str, value: str) -> None:
        try:
            self.supabase.table("bot_storage").upsert({
                "key": key,
                "value": self._encrypt(value),
                "updated_at": self._now(),
            }).execute()
        except Exception as e:
            logging.error(f"db.save 실패 ({key}): {e}")

    def load(self, key: str) -> str | None:
        try:
            res = (
                self.supabase.table("bot_storage")
                .select("value")
                .eq("key", key)
                .execute()
            )
            if res.data:
                return self._decrypt(res.data[0]["value"])
        except Exception as e:
            logging.error(f"db.load 실패 ({key}): {e}")
        return None

    def delete(self, key: str) -> None:
        try:
            self.supabase.table("bot_storage").delete().eq("key", key).execute()
        except Exception as e:
            logging.error(f"db.delete 실패 ({key}): {e}")

    def exists(self, key: str) -> bool:
        return self.load(key) is not None


class LazyDatabase:
    def __init__(self):
        self._db = None

    def _get(self) -> SecureDatabase:
        if self._db is None:
            self._db = SecureDatabase()
        return self._db

    @property
    def supabase(self):
        return self._get().supabase

    def save(self, key: str, value: str) -> None:
        self._get().save(key, value)

    def load(self, key: str) -> str | None:
        return self._get().load(key)

    def delete(self, key: str) -> None:
        self._get().delete(key)

    def exists(self, key: str) -> bool:
        return self._get().exists(key)


db = LazyDatabase()


def get_skip_keywords() -> list[str]:
    raw = db.load("skip_keywords")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def save_skip_keywords(keywords: list[str]) -> None:
    db.save("skip_keywords", json.dumps(keywords))


def load_run_history() -> list[dict]:
    raw = db.load("run_history")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def save_run_history(history: list[dict]) -> None:
    db.save("run_history", json.dumps(history))


def delete_run_stat(idx: int) -> bool:
    history = load_run_history()
    if not (0 <= idx < len(history)):
        return False
    history.pop(idx)
    save_run_history(history)
    return True


def append_run_stat(board_id: str, voted: int, skipped: int, ran_at: str, is_full_scan: bool | None = None) -> None:
    history = load_run_history()
    board_name = db.load("board_name") or board_id
    history.append({
        "board_id": board_id,
        "board_name": board_name,
        "voted": voted,
        "skipped": skipped,
        "ran_at": ran_at,
        "is_valid": True,
        "is_full_scan": is_full_scan,
    })
    db.save("run_history", json.dumps(history[-30:]))
