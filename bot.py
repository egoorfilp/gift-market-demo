import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]


def offer_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Отклонить", callback_data="reject"),
            InlineKeyboardButton("✅ Принять", callback_data="accept"),
        ]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Gift Market | Demo\n\n"
        "Тестовый бот коллекционных подарков.\n\n"
        "Команда /offer — создать демонстрационный оффер."
    )


async def offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🎁 ДЕМО — предложение о покупке\n\n"
        "Подарок: Plush Pepe #2687\n"
        "Цена: 20 GRAM\n\n"
        "Это тестовое предложение. "
        "Реальная покупка и передача NFT не выполняются.",
        reply_markup=offer_keyboard(),
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "reject":
        await query.edit_message_text(
            "❌ Демонстрационное предложение отклонено."
        )

    elif query.data == "accept":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "Передать NFT (демо)",
                    callback_data="transfer_demo",
                )
            ],
            [
                InlineKeyboardButton(
                    "Как передать?",
                    callback_data="help_demo",
                )
            ],
        ])

        await query.edit_message_text(
            "✅ ДЕМО — предложение принято!\n\n"
            "Подарок: Plush Pepe #2687\n"
            "Цена: 20 GRAM\n\n"
            "Оплата не производилась. "
            "NFT не продан и не передан.",
            reply_markup=keyboard,
        )

    elif query.data == "transfer_demo":
        await query.answer(
            "Демо: передача NFT отключена.",
            show_alert=True,
        )

    elif query.data == "help_demo":
        await query.answer(
            "Это симуляция сделки. Настоящий NFT передавать не нужно.",
            show_alert=True,
        )


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("offer", offer))
    app.add_handler(CallbackQueryHandler(button))

    app.run_polling()


if __name__ == "__main__":
    main()
