import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv, set_key

KST = timezone(timedelta(hours=9))


class KSTFormatter(logging.Formatter):
    """모든 애플리케이션 로그 시각을 KST 오프셋과 함께 표시."""

    def formatTime(self, record, datefmt=None):
        value = datetime.fromtimestamp(record.created, KST)
        if datefmt:
            return value.strftime(datefmt)
        return value.isoformat(sep=" ", timespec="milliseconds")


DEFAULTS = {
    "bot": {
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

_ROOT = Path(__file__).parent
# 실제 비밀값은 소스 코드와 분리된 프로젝트 루트의 .env에만 둔다.
# .env와 data/는 .gitignore 및 .dockerignore에서 제외된다.
ENV_FILE = _ROOT.parent / ".env"
INTEREST_PROFILE_FILE = _ROOT.parent / "data" / "interest_profile.txt"

# Everytime API client
EVERYTIME_BASE_URL = "https://api.everytime.kr"
EVERYTIME_REQUEST_TIMEOUT = 10
EVERYTIME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

# Board selection UI
BOARD_PAGE_SIZE = 10

# Page size for article listing
PAGE_NUM = 20 

# Autonomy scheduling
AUTONOMY_WINDOW_A = ((6, 0), (9, 0))
AUTONOMY_WINDOW_B = ((17, 0), (20, 0))
AUTONOMY_TREND_SEARCH_RANGES = (((5, 0), (12, 0)), ((15, 0), (23, 0)))
AUTONOMY_TREND_LOOKBACK_DAYS = 7
AUTONOMY_TREND_MAX_PAGES = 5
AUTONOMY_TREND_MIN_SAMPLES = 20
AUTONOMY_TREND_MIN_SLOT_SAMPLES = 3
AUTONOMY_UNREAD_CHECK_WAIT_SECONDS = 2 * 60
AUTONOMY_ACTIVITY_RETRY_WAIT_RANGE = (5 * 60, 15 * 60)
AUTONOMY_MAX_ACTIVITY_ATTEMPTS = 3
AUTONOMY_DAILY_RESCHEDULE_JOB_NAME = "autonomy_daily_reschedule"
AUTONOMY_BOOTSTRAP_JOB_NAME = "autonomy_bootstrap_reschedule"
AUTONOMY_TRIGGER_JOB_NAME_PREFIX = "autonomy_trigger_"
AUTONOMY_SLOT_LABELS = {"A": "오전 슬롯", "B": "오후 슬롯"}
AUTONOMY_SLOT_EMOJIS = {"A": "☀️", "B": "🌙"}


def load_env() -> None:
    load_dotenv(ENV_FILE)


def _deep_merge(base, override):
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path=None):
    if path is None:
        path = _ROOT / "config" / "config.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        user_cfg = {}
    return _deep_merge(DEFAULTS, user_cfg)


def get_telegram_token() -> str:
    return os.environ.get("TELEGRAM_TOKEN", "").strip()


def get_telegram_chat_id() -> int | None:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not raw:
        logging.error("TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.")
        return None
    try:
        return int(raw)
    except ValueError:
        logging.error("TELEGRAM_CHAT_ID는 숫자여야 합니다.")
        return None


def get_supabase_credentials() -> tuple[str, str]:
    return (
        os.environ.get("SUPABASE_URL", "").strip(),
        os.environ.get("SUPABASE_KEY", "").strip(),
    )


def get_encryption_key() -> str:
    return os.environ.get("ENCRYPTION_KEY", "").strip()


def get_gemini_settings() -> tuple[str, str, str]:
    try:
        user_profile = INTEREST_PROFILE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        user_profile = ""
    return (
        os.environ.get("GEMINI_API_KEY", "").strip(),
        user_profile,
        os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").strip(),
    )


def set_encryption_key(key: str) -> None:
    set_key(str(ENV_FILE), "ENCRYPTION_KEY", key)
    os.environ["ENCRYPTION_KEY"] = key


def build_everytime_headers(etsid: str) -> dict:
    return {
        "Host": "api.everytime.kr",
        "Connection": "keep-alive",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": EVERYTIME_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://everytime.kr",
        "Referer": "https://everytime.kr/",
        "Cookie": f"etsid={etsid};",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
