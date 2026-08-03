import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ...core.vote_runner import VoteRunner
from ...core.database import db
from ...config import BOARD_PAGE_SIZE, load_config
from .shared import _authorized


def _build_board_keyboard(boards: list[dict], page: int) -> InlineKeyboardMarkup:
    start = page * BOARD_PAGE_SIZE
    end = start + BOARD_PAGE_SIZE
    rows = [
        [InlineKeyboardButton(b["name"], callback_data=f"sb:{b['id']}")]
        for b in boards[start:end]
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ 이전", callback_data=f"bp:{page - 1}"))
    if end < len(boards):
        nav.append(InlineKeyboardButton("다음 ▶", callback_data=f"bp:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


async def cmd_setboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    if not db.exists("etsid"):
        await update.message.reply_text("⚠️ /setsession 으로 etsid를 먼저 저장하세요.")
        return

    msg = await update.message.reply_text("🔄 게시판 목록 불러오는 중...")
    loop = asyncio.get_running_loop()
    try:
        cfg = load_config()
        bot = VoteRunner(cfg, require_board=False)
        boards = await loop.run_in_executor(None, bot.get_board_list)
    except Exception as e:
        await msg.edit_text(f"❌ 게시판 목록 조회 실패: {e}")
        return

    if not boards:
        await msg.edit_text("❌ 게시판 목록을 가져올 수 없습니다. 세션을 확인하세요.")
        return

    context.user_data["boards"] = boards
    await msg.edit_text("📋 게시판을 선택하세요:", reply_markup=_build_board_keyboard(boards, 0))


async def setboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _authorized(update):
        return

    data = query.data
    if data.startswith("bp:"):
        page = int(data[3:])
        boards = context.user_data.get("boards", [])
        await query.edit_message_reply_markup(reply_markup=_build_board_keyboard(boards, page))
    elif data.startswith("sb:"):
        board_id = data[3:]
        boards = context.user_data.get("boards", [])
        board_name = next((b["name"] for b in boards if b["id"] == board_id), board_id)
        db.save("board_id", board_id)
        db.save("board_name", board_name)
        await query.edit_message_text(
            f"✅ 게시판 설정 완료!\n"
            f"📌 {board_name} ({board_id})\n\n"
            f"/vote 로 공감을 시작하세요."
        )
