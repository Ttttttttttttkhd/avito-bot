"""
Телеграм-бот для поиска дешёвых телефонов на Авито.
"""

import logging
import os
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

# ─────────────── НАСТРОЙКИ ───────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ─────────────── ЛОГИ ────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────── ШАГИ ДИАЛОГА ────────────
CHOOSE_BRAND, CHOOSE_MODEL, CHOOSE_PRICE, CHOOSE_CONDITION, CHOOSE_CITY = range(5)

# ─────────────── ДАННЫЕ ──────────────────
BRANDS = {
    "Apple (iPhone)": "iphone",
    "Samsung": "samsung",
    "Xiaomi": "xiaomi",
    "Realme": "realme",
    "POCO": "poco",
    "OnePlus": "oneplus",
    "Другой бренд": "custom",
}

PRICE_RANGES = {
    "до 5 000 ₽": (0, 5000),
    "5 000 – 10 000 ₽": (5000, 10000),
    "10 000 – 20 000 ₽": (10000, 20000),
    "20 000 – 35 000 ₽": (20000, 35000),
    "35 000 – 60 000 ₽": (35000, 60000),
    "60 000+ ₽": (60000, 0),
}

CONDITIONS = {
    "Новый": "новый",
    "Отличное": "отличное состояние",
    "Хорошее": "хорошее состояние",
    "Любое": "",
}

CITIES = {
    "Москва": "moskva",
    "Санкт-Петербург": "sankt_peterburg",
    "Новосибирск": "novosibirsk",
    "Екатеринбург": "ekaterinburg",
    "Казань": "kazan",
    "Нижний Новгород": "nizhniy_novgorod",
    "Вся Россия": "",
}


# ─────────────── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ──

def build_avito_url(query: str, price_from: int, price_to: int, city: str) -> str:
    base = f"https://www.avito.ru/{city}/telefony" if city else "https://www.avito.ru/rossiya/telefony"
    params = {"q": query}
    if price_from:
        params["pmin"] = price_from
    if price_to:
        params["pmax"] = price_to
    return base + "?" + urllib.parse.urlencode(params, encoding="utf-8")


def build_google_search_url(query: str, price_from: int, price_to: int, city: str) -> str:
    city_text = city.replace("_", " ") if city else "россия"
    price_text = ""
    if price_from and price_to:
        price_text = f" цена {price_from}-{price_to}"
    elif price_from:
        price_text = f" от {price_from} рублей"
    elif price_to:
        price_text = f" до {price_to} рублей"
    search = f"site:avito.ru {query} {city_text}{price_text} телефон"
    return "https://www.google.com/search?q=" + urllib.parse.quote(search)


def make_keyboard(options: list, columns: int = 2) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=opt, callback_data=opt) for opt in options]
    rows = [buttons[i:i+columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(rows)


# ─────────────── ХЭНДЛЕРЫ ────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Привет! Я помогу найти дешёвый телефон на Авито.\n\n"
        "Шаг 1/5 — Выбери бренд:",
        reply_markup=make_keyboard(list(BRANDS.keys()))
    )
    return CHOOSE_BRAND


async def choose_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    brand_label = query.data
    context.user_data["brand_label"] = brand_label
    context.user_data["brand_slug"] = BRANDS[brand_label]

    if brand_label == "Другой бренд":
        await query.edit_message_text("✏️ Напиши название бренда вручную:")
        return CHOOSE_MODEL

    await query.edit_message_text(
        f"✅ Бренд: {brand_label}\n\n"
        "Шаг 2/5 — Напиши модель (например: iPhone 13, Galaxy A54).\n"
        "Или напиши «любая» чтобы искать все модели бренда:"
    )
    return CHOOSE_MODEL


async def choose_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    model = update.message.text.strip()

    if context.user_data.get("brand_slug") == "custom":
        context.user_data["brand_label"] = model
        context.user_data["brand_slug"] = model.lower()
        await update.message.reply_text(
            f"✅ Бренд: {model}\n\n"
            "Шаг 2/5 — Теперь напиши модель или «любая»:"
        )
        return CHOOSE_MODEL

    context.user_data["model"] = model
    await update.message.reply_text(
        f"✅ Модель: {model}\n\n"
        "Шаг 3/5 — Выбери ценовой диапазон:",
        reply_markup=make_keyboard(list(PRICE_RANGES.keys()), columns=2)
    )
    return CHOOSE_PRICE


async def choose_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    price_label = query.data
    price_from, price_to = PRICE_RANGES[price_label]
    context.user_data["price_label"] = price_label
    context.user_data["price_from"] = price_from
    context.user_data["price_to"] = price_to

    await query.edit_message_text(
        f"✅ Цена: {price_label}\n\n"
        "Шаг 4/5 — Выбери состояние телефона:",
        reply_markup=make_keyboard(list(CONDITIONS.keys()), columns=2)
    )
    return CHOOSE_CONDITION


async def choose_condition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    condition_label = query.data
    context.user_data["condition_label"] = condition_label
    context.user_data["condition"] = CONDITIONS[condition_label]

    await query.edit_message_text(
        f"✅ Состояние: {condition_label}\n\n"
        "Шаг 5/5 — Выбери город:",
        reply_markup=make_keyboard(list(CITIES.keys()), columns=2)
    )
    return CHOOSE_CITY


async def choose_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    city_label = query.data
    city_slug = CITIES[city_label]
    context.user_data["city_label"] = city_label
    context.user_data["city_slug"] = city_slug

    brand = context.user_data.get("brand_label", "")
    model = context.user_data.get("model", "")
    condition = context.user_data.get("condition", "")
    price_from = context.user_data.get("price_from", 0)
    price_to = context.user_data.get("price_to", 0)

    if model.lower() == "любая":
        search_query = brand
    else:
        search_query = f"{brand} {model}".strip()

    if condition:
        search_query += f" {condition}"

    avito_url = build_avito_url(search_query, price_from, price_to, city_slug)
    google_url = build_google_search_url(search_query, price_from, price_to, city_slug)

    price_label = context.user_data.get("price_label", "не указана")
    summary = (
        f"🔍 *Параметры поиска:*\n"
        f"📱 Устройство: {search_query}\n"
        f"💰 Цена: {price_label}\n"
        f"✨ Состояние: {context.user_data.get('condition_label', '—')}\n"
        f"📍 Город: {city_label}\n\n"
        f"Выбери, где искать:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Открыть Авито", url=avito_url)],
        [InlineKeyboardButton("🔎 Поиск через Google", url=google_url)],
        [InlineKeyboardButton("🔄 Новый поиск", callback_data="restart")],
    ])

    await query.edit_message_text(summary, parse_mode="Markdown", reply_markup=keyboard)
    return ConversationHandler.END


async def restart_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "🔄 Начинаем заново!\n\nШаг 1/5 — Выбери бренд:",
        reply_markup=make_keyboard(list(BRANDS.keys()))
    )
    return CHOOSE_BRAND


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Поиск отменён. Напиши /start чтобы начать заново.")
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться ботом:*\n\n"
        "1. Напиши /start\n"
        "2. Выбери бренд телефона\n"
        "3. Введи конкретную модель или «любая»\n"
        "4. Выбери ценовой диапазон\n"
        "5. Выбери состояние (новый / б/у)\n"
        "6. Выбери город\n"
        "7. Получи готовые ссылки на Авито 🎉\n\n"
        "Команды:\n"
        "/start — новый поиск\n"
        "/cancel — отменить\n"
        "/help — эта справка",
        parse_mode="Markdown"
    )


# ─────────────── ЗАПУСК ──────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_BRAND:     [CallbackQueryHandler(choose_brand)],
            CHOOSE_MODEL:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_model),
                CallbackQueryHandler(choose_brand),
            ],
            CHOOSE_PRICE:     [CallbackQueryHandler(choose_price)],
            CHOOSE_CONDITION: [CallbackQueryHandler(choose_condition)],
            CHOOSE_CITY:      [CallbackQueryHandler(choose_city)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(restart_from_button, pattern="^restart$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(restart_from_button, pattern="^restart$"))

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
