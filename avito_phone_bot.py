"""
Телеграм-бот для поиска телефонов на Авито через RSS.
Автоматически присылает новые объявления каждые 30 минут.
"""
 
import logging
import os
import urllib.parse
import asyncio
import feedparser
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)
 
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHECK_INTERVAL = 30 * 60
SEEN_FILE = "seen_items.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
CHOOSE_BRAND, CHOOSE_MODEL, CHOOSE_PRICE, CHOOSE_CONDITION, CHOOSE_CITY = range(5)
 
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
 
 
def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}
 
def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
 
 
def build_avito_url(query, price_from, price_to, city):
    city_part = city if city else "rossiya"
    base = f"https://www.avito.ru/{city_part}/telefony"
    params = {"q": query, "s": 104}
    if price_from:
        params["pmin"] = price_from
    if price_to:
        params["pmax"] = price_to
    return f"{base}?{urllib.parse.urlencode(params, encoding='utf-8')}"
 
 
def build_rss_url(query, price_from, price_to, city):
    city_part = city if city else "rossiya"
    base = f"https://www.avito.ru/rss/{city_part}/telefony"
    params = {"q": query}
    if price_from:
        params["pmin"] = price_from
    if price_to:
        params["pmax"] = price_to
    return f"{base}?{urllib.parse.urlencode(params, encoding='utf-8')}"
 
 
async def check_rss(rss_url, user_id, seen):
    try:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, rss_url)
        new_items = []
        user_seen = seen.get(user_id, [])
        for entry in feed.entries[:10]:
            item_id = entry.get("id") or entry.get("link", "")
            if item_id and item_id not in user_seen:
                new_items.append({
                    "id": item_id,
                    "title": entry.get("title", "Без названия"),
                    "link": entry.get("link", ""),
                })
        return new_items
    except Exception as e:
        logger.error(f"RSS ошибка: {e}")
        return []
 
 
async def monitor_loop(app):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        logger.info("Проверяю RSS...")
        subscriptions = load_json(SUBSCRIPTIONS_FILE)
        seen = load_json(SEEN_FILE)
 
        for user_id, sub in subscriptions.items():
            if not sub.get("active"):
                continue
            rss_url = sub.get("rss_url")
            if not rss_url:
                continue
 
            new_items = await check_rss(rss_url, user_id, seen)
            if new_items:
                user_seen = seen.get(user_id, [])
                for item in new_items:
                    user_seen.append(item["id"])
                seen[user_id] = user_seen[-200:]
                save_json(SEEN_FILE, seen)
 
                text = f"🔔 *Новые объявления ({sub.get('label', '')}):\n\n*"
                for item in new_items[:5]:
                    text += f"📱 [{item['title']}]({item['link']})\n\n"
 
                try:
                    await app.bot.send_message(
                        chat_id=int(user_id),
                        text=text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки {user_id}: {e}")
 
 
def make_keyboard(options, columns=2):
    buttons = [InlineKeyboardButton(text=opt, callback_data=opt) for opt in options]
    rows = [buttons[i:i+columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(rows)
 
 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Привет! Настрою автоматический поиск телефонов на Авито.\n"
        "Как только появятся новые объявления — сразу пришлю!\n\n"
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
        await query.edit_message_text("✏️ Напиши название бренда:")
        return CHOOSE_MODEL
 
    await query.edit_message_text(
        f"✅ Бренд: {brand_label}\n\n"
        "Шаг 2/5 — Напиши модель (например: iPhone 13).\n"
        "Или «любая» для всех моделей:"
    )
    return CHOOSE_MODEL
 
 
async def choose_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    model = update.message.text.strip()
 
    if context.user_data.get("brand_slug") == "custom":
        context.user_data["brand_label"] = model
        context.user_data["brand_slug"] = model.lower()
        await update.message.reply_text(f"✅ Бренд: {model}\n\nШаг 2/5 — Напиши модель или «любая»:")
        return CHOOSE_MODEL
 
    context.user_data["model"] = model
    await update.message.reply_text(
        f"✅ Модель: {model}\n\nШаг 3/5 — Выбери ценовой диапазон:",
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
        f"✅ Цена: {price_label}\n\nШаг 4/5 — Состояние:",
        reply_markup=make_keyboard(list(CONDITIONS.keys()), columns=2)
    )
    return CHOOSE_CONDITION
 
 
async def choose_condition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["condition_label"] = query.data
    context.user_data["condition"] = CONDITIONS[query.data]
 
    await query.edit_message_text(
        f"✅ Состояние: {query.data}\n\nШаг 5/5 — Выбери город:",
        reply_markup=make_keyboard(list(CITIES.keys()), columns=2)
    )
    return CHOOSE_CITY
 
 
async def choose_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    city_label = query.data
    city_slug = CITIES[city_label]
 
    brand = context.user_data.get("brand_label", "")
    model = context.user_data.get("model", "")
    condition = context.user_data.get("condition", "")
    price_from = context.user_data.get("price_from", 0)
    price_to = context.user_data.get("price_to", 0)
    price_label = context.user_data.get("price_label", "")
 
    search_query = brand if model.lower() == "любая" else f"{brand} {model}".strip()
    if condition:
        search_query += f" {condition}"
 
    rss_url = build_rss_url(search_query, price_from, price_to, city_slug)
    avito_url = build_avito_url(search_query, price_from, price_to, city_slug)
    label = f"{search_query} | {price_label} | {city_label}"
    user_id = str(query.from_user.id)
 
    subscriptions = load_json(SUBSCRIPTIONS_FILE)
    subscriptions[user_id] = {
        "rss_url": rss_url,
        "avito_url": avito_url,
        "label": label,
        "active": True,
        "created": datetime.now().isoformat(),
    }
    save_json(SUBSCRIPTIONS_FILE, subscriptions)
 
    summary = (
        f"✅ *Подписка активирована!*\n\n"
        f"📱 {search_query}\n"
        f"💰 {price_label}\n"
        f"✨ {context.user_data.get('condition_label', '—')}\n"
        f"📍 {city_label}\n\n"
        f"🔔 Буду присылать новые объявления каждые 30 минут!\n\n"
        f"/check — проверить прямо сейчас\n"
        f"/stop — остановить\n"
        f"/status — статус подписки"
    )
 
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Открыть Авито", url=avito_url)],
        [InlineKeyboardButton("🔄 Изменить поиск", callback_data="restart")],
    ])
 
    await query.edit_message_text(summary, parse_mode="Markdown", reply_markup=keyboard)
    return ConversationHandler.END
 
 
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subscriptions = load_json(SUBSCRIPTIONS_FILE)
    if user_id in subscriptions:
        subscriptions[user_id]["active"] = False
        save_json(SUBSCRIPTIONS_FILE, subscriptions)
        await update.message.reply_text("⏹ Уведомления остановлены. Напиши /start для нового поиска.")
    else:
        await update.message.reply_text("Нет активных подписок. Напиши /start.")
 
 
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sub = load_json(SUBSCRIPTIONS_FILE).get(user_id)
    if not sub:
        await update.message.reply_text("Нет подписок. Напиши /start.")
        return
    status = "🟢 Активна" if sub.get("active") else "🔴 Остановлена"
    await update.message.reply_text(
        f"📋 *Подписка:*\n{status}\n🔍 {sub.get('label', '—')}\n\n"
        f"/check — проверить сейчас\n/stop — остановить\n/start — изменить",
        parse_mode="Markdown"
    )
 
 
async def check_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sub = load_json(SUBSCRIPTIONS_FILE).get(user_id)
    if not sub or not sub.get("active"):
        await update.message.reply_text("Нет активных подписок. Напиши /start.")
        return
 
    await update.message.reply_text("🔍 Проверяю Авито прямо сейчас...")
    seen = load_json(SEEN_FILE)
    new_items = await check_rss(sub.get("rss_url"), user_id, seen)
 
    if new_items:
        user_seen = seen.get(user_id, [])
        for item in new_items:
            user_seen.append(item["id"])
        seen[user_id] = user_seen[-200:]
        save_json(SEEN_FILE, seen)
 
        text = f"🔔 *Найдено {len(new_items)} новых объявлений:*\n\n"
        for item in new_items[:5]:
            text += f"📱 [{item['title']}]({item['link']})\n\n"
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text(
            "😕 Новых объявлений пока нет. Проверю снова через 30 минут.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🛒 Открыть Авито", url=sub.get("avito_url", "https://avito.ru"))
            ]])
        )
 
 
async def restart_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "🔄 Новый поиск!\n\nШаг 1/5 — Выбери бренд:",
        reply_markup=make_keyboard(list(BRANDS.keys()))
    )
    return CHOOSE_BRAND
 
 
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Отменено. Напиши /start.")
    return ConversationHandler.END
 
 
async def post_init(app):
    asyncio.create_task(monitor_loop(app))
 
 
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
 
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_BRAND:     [CallbackQueryHandler(choose_brand)],
            CHOOSE_MODEL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_model)],
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
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("check", check_now_cmd))
    app.add_handler(CallbackQueryHandler(restart_from_button, pattern="^restart$"))
 
    logger.info("Бот запущен с RSS мониторингом!")
    app.run_polling()
 
 
if __name__ == "__main__":
    main()
