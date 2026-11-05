import os
import re
import html
import uuid
import sqlite3
import logging
from decimal import Decimal, InvalidOperation

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LinkPreviewOptions,
)

from telegram.constants import ParseMode

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# CONFIG
# =========================

TOKEN = os.environ["BOT_TOKEN"]

GRAM_EMOJI_ID = os.getenv(
    "GRAM_EMOJI_ID",
    "5318901904686754959",
)

DB_PATH = os.getenv(
    "DB_PATH",
    "offers.db",
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# DATABASE
# =========================

def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id TEXT PRIMARY KEY,
                owner INTEGER NOT NULL,
                buyer TEXT NOT NULL,
                gift_name TEXT NOT NULL,
                gift_number TEXT NOT NULL,
                gift_url TEXT NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                recipient INTEGER
            )
            """
        )


def save_offer(offer):
    with db() as connection:
        connection.execute(
            """
            INSERT INTO offers (
                id,
                owner,
                buyer,
                gift_name,
                gift_number,
                gift_url,
                price,
                currency,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer["id"],
                offer["owner"],
                offer["buyer"],
                offer["gift_name"],
                offer["gift_number"],
                offer["gift_url"],
                offer["price"],
                offer["currency"],
                "pending",
            ),
        )


def get_offer(offer_id):
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()

    return dict(row) if row else None


def get_user_offers(user_id):
    with db() as connection:
        rows = connection.execute(
            """
            SELECT * FROM offers
            WHERE owner = ?
            ORDER BY rowid DESC
            LIMIT 30
            """,
            (user_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def update_offer_status(offer_id, old_status, new_status, recipient=None):
    with db() as connection:
        result = connection.execute(
            """
            UPDATE offers
            SET status = ?, recipient = ?
            WHERE id = ? AND status = ?
            """,
            (
                new_status,
                recipient,
                offer_id,
                old_status,
            ),
        )

        return result.rowcount > 0


# =========================
# GIFT
# =========================

def parse_gift(text):
    match = re.search(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)",
        text.strip(),
        re.IGNORECASE,
    )

    if not match:
        return None

    slug = match.group(1)
    number = match.group(2)

    name = re.sub(
        r"(?<=[a-z])(?=[A-Z])",
        " ",
        slug,
    )

    return {
        "gift_name": name,
        "gift_number": number,
        "gift_url": f"https://t.me/nft/{slug}-{number}",
    }


def gift_title(offer):
    return (
        f'{offer["gift_name"]} '
        f'#{offer["gift_number"]}'
    )


# =========================
# EMOJI / PRICE
# =========================

def gram_emoji():
    return (
        f'<tg-emoji emoji-id="{GRAM_EMOJI_ID}">'
        "💎"
        "</tg-emoji>"
    )


def price_html(offer):
    price = html.escape(str(offer["price"]))

    if offer["currency"] == "GRAM":
        return f"{price} {gram_emoji()} GRAM"

    return f"{price} TON"


def price_plain(offer):
    if offer["currency"] == "GRAM":
        return f'{offer["price"]} 💎 GRAM'

    return f'{offer["price"]} TON'


def gift_link_html(offer):
    url = html.escape(
        offer["gift_url"],
        quote=True,
    )

    title = html.escape(gift_title(offer))

    return f'<a href="{url}">{title}</a>'


def preview_options():
    return LinkPreviewOptions(
        is_disabled=False,
        show_above_text=True,
        prefer_large_media=True,
    )


# =========================
# OFFER TEXTS
# =========================

def pending_text(offer):
    buyer = html.escape(offer["buyer"])

    return (
        f'{gift_link_html(offer)}\n\n'
        f'Пользователь <b>{buyer}</b> предлагает '
        f'Вам <b>{price_html(offer)}</b> '
        f'за подарок <b>{html.escape(gift_title(offer))}</b>.'
    )


def accepted_text(offer):
    return (
        f'{gift_link_html(offer)}\n\n'
        "<b>Предложение принято!</b>\n\n"
        f'Подарок: <b>{html.escape(gift_title(offer))}</b>\n'
        f'Стоимость: <b>{price_html(offer)}</b>\n\n'
        "Статус: <b>Ожидается оплата</b>."
    )


def rejected_text(offer):
    return (
        f'{gift_link_html(offer)}\n\n'
        "<b>Предложение отклонено.</b>\n\n"
        f'Стоимость: <b>{price_html(offer)}</b>'
    )


def offer_text(offer):
    if offer["status"] == "accepted":
        return accepted_text(offer)

    if offer["status"] == "rejected":
        return rejected_text(offer)

    return pending_text(offer)


# =========================
# KEYBOARDS
# =========================

def main_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Создать оффер",
                    callback_data="create",
                )
            ],
            [
                InlineKeyboardButton(
                    "Мои офферы",
                    callback_data="my_offers",
                )
            ],
        ]
    )


def currency_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 GRAM",
                    callback_data="currency:GRAM",
                ),
                InlineKeyboardButton(
                    "TON",
                    callback_data="currency:TON",
                ),
            ]
        ]
    )


def offer_keyboard(offer):
    offer_id = offer["id"]

    if offer["status"] == "pending":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Отклонить",
                        callback_data=f"reject:{offer_id}",
                    ),
                    InlineKeyboardButton(
                        "Принять",
                        callback_data=f"accept:{offer_id}",
                    ),
                ]
            ]
        )

    if offer["status"] == "accepted":
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Статус оплаты",
                        callback_data=f"payment:{offer_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Как завершить сделку?",
                        callback_data=f"help:{offer_id}",
                    )
                ],
            ]
        )

    return None


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "<b>Gift Market</b>\n\n"
        "Создавай предложения о покупке "
        "коллекционных подарков Telegram.\n\n"
        "Выбери действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


async def create_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = "gift"

    message = (
        "<b>Создание предложения</b>\n\n"
        "От
