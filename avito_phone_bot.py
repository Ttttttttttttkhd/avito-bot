"""
Бот с Web App кнопкой.
Добавь WEBAPP_URL в переменные Railway — это URL твоего index.html.
"""

import logging
import os
import urllib.parse
import asyncio
import feedparser
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")  # URL страницы index.html
CHECK_INTERVAL = 30 * 60
SEEN_FILE = "seen_items.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_avito_url(query, price_to, city):
    city_part = city if city else "rossiya"
    base = f"https://www.avito.ru/{city_part}/telefony"
    params = {"q": query, "s": 104}
    if price_to:
        params["pmax"] = price_to
    return f"{base}?{urllib.parse.urlencode(params, encoding='utf-8')}"


def build_rss_url(query, price_to, city):
    city_part = city if city else "rossiya"
    base = f"https://www.avito.ru/rss/{city_part}/telefony"
    params = {"q": query}
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
            new_items = await check_rss(sub.get("rss_url", ""), user_id, seen)
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔍 Открыть поиск",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])
    await update.message.reply_text(
        "👋 Привет! Нажми кнопку ниже чтобы настроить поиск телефонов на Авито.\n\n"
        "Я буду присылать новые объявления каждые 30 минут 🔔",
        reply_markup=keyboard
    )


async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем данные из Web App."""
    data = json.loads(update.effective_message.web_app_data.data)
    user_id = str(update.effective_user.id)

    query = data.get("query", "")
    price_to = data.get("price_to", 0)
    condition = data.get("condition", "")
    city = data.get("city", "")
    city_label = data.get("cityLabel", "Вся Россия")
    model = data.get("model", "")

    if condition:
        search_query = f"{query} {condition}".strip()
    else:
        search_query = query

    rss_url = build_rss_url(search_query, price_to, city)
    avito_url = build_avito_url(search_query, price_to, city)
    label = f"{query} | до {price_to:,} ₽ | {city_label}".replace(",", " ")

    subscriptions = load_json(SUBSCRIPTIONS_FILE)
    subscriptions[user_id] = {
        "rss_url": rss_url,
        "avito_url": avito_url,
        "label": label,
        "active": True,
        "created": datetime.now().isoformat(),
    }
    save_json(SUBSCRIPTIONS_FILE, subscriptions)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛒 Открыть Авито", url=avito_url)
    ], [
        InlineKeyboardButton("🔍 Изменить поиск", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])

    await update.message.reply_text(
        f"✅ *Подписка активирована!*\n\n"
        f"🔍 {label}\n\n"
        f"Буду присылать новые объявления каждые 30 минут!\n\n"
        f"/check — проверить прямо сейчас\n"
        f"/stop — остановить уведомления",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subscriptions = load_json(SUBSCRIPTIONS_FILE)
    if user_id in subscriptions:
        subscriptions[user_id]["active"] = False
        save_json(SUBSCRIPTIONS_FILE, subscriptions)
        await update.message.reply_text("⏹ Уведомления остановлены. Напиши /start чтобы начать заново.")
    else:
        await update.message.reply_text("Нет активных подписок. Напиши /start.")


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


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    sub = load_json(SUBSCRIPTIONS_FILE).get(user_id)
    if not sub:
        await update.message.reply_text("Нет подписок. Напиши /start.")
        return
    status = "🟢 Активна" if sub.get("active") else "🔴 Остановлена"
    await update.message.reply_text(
        f"📋 *Подписка:*\n{status}\n🔍 {sub.get('label', '—')}\n\n"
        f"/check — проверить\n/stop — остановить\n/start — изменить",
        parse_mode="Markdown"
    )


async def post_init(app):
    asyncio.create_task(monitor_loop(app))


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("check", check_now_cmd))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    logger.info("Бот с Web App запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
