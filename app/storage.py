import os
import logging
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from dotenv import set_key
from supabase import create_client

from .settings import ENV_FILE, load_env

_ENV_FILE = str(ENV_FILE)


class SecureStorage:
    def __init__(self):
        load_env()

        url = os.environ.get("SUPABASE_URL", "").strip()
        key_sb = os.environ.get("SUPABASE_KEY", "").strip()
        if not url or not key_sb:
            raise RuntimeError("SUPABASE_URL 또는 SUPABASE_KEY 환경변수가 설정되지 않았습니다.")

        self.supabase = create_client(url, key_sb)

        enc_key = os.environ.get("ENCRYPTION_KEY", "").strip()
        if not enc_key:
            enc_key = Fernet.generate_key().decode()
            set_key(_ENV_FILE, "ENCRYPTION_KEY", enc_key)
            os.environ["ENCRYPTION_KEY"] = enc_key
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
            logging.error(f"storage.save 실패 ({key}): {e}")

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
            logging.error(f"storage.load 실패 ({key}): {e}")
        return None

    def delete(self, key: str) -> None:
        try:
            self.supabase.table("bot_storage").delete().eq("key", key).execute()
        except Exception as e:
            logging.error(f"storage.delete 실패 ({key}): {e}")

    def exists(self, key: str) -> bool:
        return self.load(key) is not None
