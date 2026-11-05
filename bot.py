import os
import re
import uuid
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
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]

offers = {}

# Сюда позже добавим ID синего эмодзи GRAM
GRAM_EMOJI_ID = os.getenv("GRAM_EMOJI_ID", "")


def parse_gift(text):
    match = re.search(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)-(\d+)",
        text.strip(),
        re.IGNORECASE,
    )

    if match:
        collection = match.group(1)
        number = match.group(2)

        return {
            "title": f"{collection} #{number}",
            "url": f"https://t.me/nft/{collection}-{number}",
        }

    if text.startswith("https://"):
        return {
            "title": "NFT",
            "url": text,
        }

    return None


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Создать оффер", callback_data="create")],
        [InlineKeyboardButton("Мои офферы", callback_data="my_offers")],
    ])


def offer_text(offer):
    buyer = offer["buyer"]
    price = offer["price"]
    currency = offer["currency"]
    title = offer["title"]

    if offer["status"] == "accepted":
        return (
            f"Предложение принято.\n\n"
            f"{title}\n"
            f"Цена: {price} {currency}\n\n"
            "Оплата не подтверждена."
        )

    if offer["status"] == "rejected":
        return "Предложение отклонено."

    return (
        f"Пользователь {buyer} предлагает Вам "
        f"{price} {currency} за подарок {title}."
    )


def offer_buttons(offer_id):
    offer = offers[offer_id]

    if offer["status"] != "pending":
        return None

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Отклонить",
                callback_data=f"
