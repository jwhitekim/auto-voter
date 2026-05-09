import asyncio
import os

from dotenv import load_dotenv
from telegram import Update

load_dotenv()
ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])


def _authorized(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID


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
