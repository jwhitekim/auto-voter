from pathlib import Path

import yaml

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

_ROOT = Path(__file__).parent.parent


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
