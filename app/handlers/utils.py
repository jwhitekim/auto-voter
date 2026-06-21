import asyncio
import logging
import os

from telegram import Update

from ..settings import load_env

load_env()


def _allowed_chat_id() -> int | None:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not raw:
        logging.error("TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.")
        return None
    try:
        return int(raw)
    except ValueError:
        logging.error("TELEGRAM_CHAT_ID는 숫자여야 합니다.")
        return None


def _authorized(update: Update) -> bool:
    allowed_chat_id = _allowed_chat_id()
    return allowed_chat_id is not None and update.effective_chat.id == allowed_chat_id


async def _safe_edit(msg, text: str) -> None:
    for _ in range(2):
        try:
            await msg.edit_text(text)
            return
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                await asyncio.sleep(1)
            else:
                return
