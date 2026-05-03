import os
import json
import logging
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv, set_key

_ENV_FILE = ".env"
_STORAGE_FILE = "encrypted_storage.json"


class SecureStorage:
    def __init__(self):
        load_dotenv()
        key = os.environ.get("ENCRYPTION_KEY", "").strip()
        if not key:
            key = Fernet.generate_key().decode()
            set_key(_ENV_FILE, "ENCRYPTION_KEY", key)
            os.environ["ENCRYPTION_KEY"] = key
            logging.info("새 암호화 키를 생성했습니다.")
        self._fernet = Fernet(key.encode())
        self._path = Path(_STORAGE_FILE)

    def _load_raw(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_raw(self, data: dict):
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def save(self, key: str, value: str):
        data = self._load_raw()
        data[key] = self._fernet.encrypt(value.encode()).decode()
        self._save_raw(data)

    def load(self, key: str) -> str | None:
        data = self._load_raw()
        if key not in data:
            return None
        try:
            return self._fernet.decrypt(data[key].encode()).decode()
        except Exception:
            logging.error(f"복호화 실패: {key}")
            return None

    def delete(self, key: str):
        data = self._load_raw()
        data.pop(key, None)
        self._save_raw(data)

    def exists(self, key: str) -> bool:
        return key in self._load_raw()
