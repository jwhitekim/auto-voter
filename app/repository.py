import json

from .storage import SecureStorage

storage = SecureStorage()


def get_skip_keywords() -> list[str]:
    raw = storage.load("skip_keywords")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def save_skip_keywords(keywords: list[str]) -> None:
    storage.save("skip_keywords", json.dumps(keywords))


def load_run_history() -> list[dict]:
    raw = storage.load("run_history")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def save_run_history(history: list[dict]) -> None:
    storage.save("run_history", json.dumps(history))


def delete_run_stat(idx: int) -> bool:
    history = load_run_history()
    if not (0 <= idx < len(history)):
        return False
    history.pop(idx)
    save_run_history(history)
    return True


def append_run_stat(board_id: str, voted: int, skipped: int, ran_at: str, is_full_scan: bool | None = None) -> None:
    history = load_run_history()
    board_name = storage.load("board_name") or board_id
    history.append({
        "board_id": board_id, "board_name": board_name,
        "voted": voted, "skipped": skipped,
        "ran_at": ran_at, "is_valid": True,
        "is_full_scan": is_full_scan,
    })
    storage.save("run_history", json.dumps(history[-30:]))
