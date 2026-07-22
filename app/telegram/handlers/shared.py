import asyncio

from telegram import Update

from ...config import get_telegram_chat_id, load_env

load_env()


def _authorized(update: Update) -> bool:
    allowed_chat_id = get_telegram_chat_id()
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
