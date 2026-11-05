import os
import re
import uuid
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]

# Офферы хранятся в памяти.
# После перезапуска бота они сбрасываются.
offers = {}


def parse_gift(value):
    value = value.strip()

    match = re.search(
        r"(?:https?://)?t\.me/nft/([A-Za-z0-9_-]+)",
        value,
        re.IGNORECASE,
    )

    if match:
        value = match.group(1)

    match = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9_-]*?)-(\d+)",
        value,
    )

    if not match:
        return None

    name = match.group(1)
    number = match.group(2)

    return {
        "name": name,
        "number": number,
        "url": f"https://t.me/nft/{name}-{number}",
    }


def offer_text(offer):
    return (
        "🎁 Предложение о покупке подарка\n\n"
        f"Подарок: {offer['name']} #{offer['number']}\n"
        f"Предложенная цена: {offer['price']}\n\n"
        "Статус: ожидает ответа.\n"
        "Принятие предложения не означает оплату "
        "или передачу подарка."
    )


def offer_keyboard(offer_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"reject:{offer_id}",
            ),
            InlineKeyboardButton(
                "✅ Принять",
                callback_data=f"accept:{offer_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎁 Посмотреть подарок",
                url=offers[offer_id]["url"],
            )
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎁 Gift Market\n\n"
        "Создавайте предложения о покупке "
        "коллекционных подарков Telegram.\n\n"
        "Для создания предложения отправьте /offer."
    )


async def offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "gift"

    await update.message.reply_text(
        "🎁 Создание предложения\n\n"
        "Отправьте ссылку на коллекционный подарок "
        "или его название и номер.\n\n"
        "Например:\n"
        "https://t.me/nft/PlushPepe-2687"
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    step = context.user_data.get("step")

    if step == "gift":
        gift = parse_gift(update.message.text)

        if not gift:
            await update.message.reply_text(
                "Не удалось распознать подарок.\n\n"
                "Отправьте ссылку вида:\n"
                "https://t.me/nft/PlushPepe-2687"
            )
            return

        context.user_data["gift"] = gift
        context.user_data["step"] = "price"

        await update.message.reply_text(
            f"Подарок: {gift['name']} #{gift['number']}\n\n"
            "Укажите предлагаемую цену и валюту.\n"
            "Например: 20 TON"
        )

    elif step == "price":
        price = update.message.text.strip()

        if not re.fullmatch(
            r"\d+(?:[.,]\d+)?\s+[A-Za-zА-Яа-яЁё]+",
            price,
        ):
            await update.message.reply_text(
                "Укажите сумму и валюту.\n"
                "Например: 20 TON"
            )
            return

        gift = context.user_data["gift"]

        offer_id = uuid.uuid4().hex[:12]

        offers[offer_id] = {
            **gift,
            "price": price,
            "owner": update.effective_user.id,
            "status": "pending",
        }

        context.user_data["step"] = None

        await update.message.reply_text(
            "✅ Предложение создано!\n\n"
            + offer_text(offers[offer_id])
            + "\n\n"
            "Чтобы отправить его человеку:\n"
            "1. Откройте переписку.\n"
            "2. Введите @username_бота и пробел.\n"
            "3. Выберите предложение из списка.",
            reply_markup=offer_keyboard(offer_id),
        )


async def inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.inline_query

    results = []

    for offer_id, item in list(offers.items()):
        if item["owner"] != query.from_user.id:
            continue

        if item["status"] != "pending":
            continue

        results.append(
            InlineQueryResultArticle(
                id=offer_id,
                title=f"{item['name']} #{item['number']}",
                description=f"Цена: {item['price']}",
                input_message_content=InputTextMessageContent(
                    offer_text(item)
                ),
                reply_markup=offer_keyboard(offer_id),
            )
        )

    await query.answer(
        results[:50],
        cache_time=0,
        is_personal=True,
    )


async def button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    action, _, offer_id = query.data.partition(":")

    item = offers.get(offer_id)

    if not item:
        await query.answer(
            "Предложение больше недоступно.",
            show_alert=True,
        )
        return

    if action == "accept":
        if item["status"] != "pending":
            await query.answer(
                "Предложение уже обработано.",
                show_alert=True,
            )
            return

        item["status"] = "accepted"

        await query.answer(
            "Предложение принято. "
            "Оплата и передача подарка ещё не выполнены.",
            show_alert=True,
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Как это работает?",
                    callback_data=f"help:{offer_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Посмотреть подарок",
                    url=item["url"],
                )
            ],
        ])

        await query.edit_message_text(
            "✅ Предложение принято!\n\n"
            f"Подарок: {item['name']} #{item['number']}\n"
            f"Цена: {item['price']}\n\n"
            "Статус: ожидается завершение сделки.\n\n"
            "Оплата не подтверждена. "
            "Подарок не передан.",
            reply_markup=keyboard,
        )

    elif action == "reject":
        if item["status"] != "pending":
            await query.answer(
                "Предложение уже обработано.",
                show_alert=True,
            )
            return

        item["status"] = "rejected"

        await query.answer("Предложение отклонено.")

        await query.edit_message_text(
            "❌ Предложение отклонено.\n\n"
            f"Подарок: {item['name']} #{item['number']}"
        )

    elif action == "help":
        await query.answer(
            "Принятие предложения не переводит деньги "
            "и не передаёт NFT. "
            "Завершайте сделку через проверенную площадку "
            "с подтверждением оплаты.",
            show_alert=True,
        )


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("offer", offer))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(CallbackQueryHandler(button))

    app.run_polling()


if __name__ == "__main__":
    main()
