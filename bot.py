import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from collections import deque

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import importlib

#setting log
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

#token bot

API_TOKEN = "insert token"

user_message_times: Dict[int, List[float]] = {}
spam_blocked_users: Dict[int, float] = {}

MAX_MESSAGES = 7
INTERVAL_SECONDS = 3
BLOCK_DURATION = 30

#safe import madule
def safe_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except Exception as e:
        logger.warning(f" module {module_name} unavailable: {e}")
        return None

digikala = safe_import("digikala_optimized")
ebay = safe_import("ebay_optimized")
web_global = safe_import("web_mimic_optimized")

# Task Queue Management
class ManagerQueue:
    def __init__(self, name: str, max_concurrency: int = 3):
        self.name = name
        self.max_concurrency = max_concurrency
        self.current_running = 0
        self.lock = asyncio.Lock()
        self.queue = asyncio.Queue()

    async def submit(self, job: Dict[str, Any]) -> Dict[str, Any]:
        async with self.lock:
            if self.current_running < self.max_concurrency:
                self.current_running += 1
                asyncio.create_task(self._run_job(job))
                return {"status": "running", "position": 0}
            else:
                await self.queue.put(job)
                pos = self.queue.qsize()
                return {"status": "queued", "position": pos}

    async def _run_job(self, job: Dict[str, Any]):
        try:
            handler = job.get("handler_coroutine")
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                await asyncio.to_thread(handler)
        except Exception as e:
            logger.exception(f"❌Job Execution Error{self.name}: {e}")
        finally:
            async with self.lock:
                self.current_running = max(0, self.current_running - 1)
                if not self.queue.empty():
                    next_job = await self.queue.get()
                    self.current_running += 1
                    asyncio.create_task(self._run_job(next_job))

    async def cancel(self, chat_id: int) -> bool:
        removed = False
        try:
            q_deque: deque = self.queue._queue  # type: ignore[attr-defined]
            new_deque = deque([job for job in q_deque if job.get("chat_id") != chat_id])
            if len(new_deque) != len(q_deque):
                removed = True
            self.queue._queue = new_deque  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"⚠️Error Canceling{self.name}: {e}")
        return removed

    def is_user_queued(self, chat_id: int) -> bool:
        try:
            q_deque: deque = self.queue._queue  # type: ignore[attr-defined]
            return any(job.get("chat_id") == chat_id for job in q_deque)
        except Exception:
            return False


#Task Queue & status
managers = {
    "digikala": ManagerQueue("digikala", max_concurrency=3),
    "ebay": ManagerQueue("ebay", max_concurrency=3),
    "global": ManagerQueue("global", max_concurrency=3),
}

user_state: Dict[int, Dict[str, Any]] = {}
user_running: Dict[int, bool] = {}

# کیبوردها
def start_keyboard():
    keyboard = [
        [KeyboardButton("ℹ️ Helo"), KeyboardButton("🛒 Shops")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def main_keyboard():
    keyboard = [
        [KeyboardButton("🔎 Digikala")],
        [KeyboardButton("🔎 eBay")],
        [KeyboardButton("🔎 Global (link + name)")],
        [KeyboardButton("❌ Cancel Operation")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# final results formatting
def format_results_html(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title") or "No Title"
        url = r.get("url") or "#"
        price = r.get("price") or r.get("price_toman") or r.get("price_dollar") or "Unknown"
        if isinstance(price, (int, float)):
            price = f"{price:,} تومان"
        elif isinstance(price, str) and price.replace(",", "").isdigit():
            price = f"{price} تومان"
        title_esc = title.replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"{i}. <a href=\"{url}\">{title_esc}</a>\n💰 قیمت: {price}")
    return "\n\n".join(lines)

#run safe scraper
async def call_scraper(scraper_key: str, *, query: str, link: Optional[str] = None, max_results: int = 5):
    loop = asyncio.get_event_loop()
    try:
        if scraper_key == "digikala":
            func = getattr(digikala, "search", None)
            args = (query,)
        elif scraper_key == "ebay":
            func = getattr(ebay, "search", None)
            args = (query,)
        elif scraper_key == "global":
            func = getattr(web_global, "search_with_link", None) or getattr(web_global, "search", None)
            args = (link, query)
        else:
            raise RuntimeError("key scraper is invalid.")

        if not func:
            raise RuntimeError(f"Search function not found in the module.{scraper_key}")

        if asyncio.iscoroutinefunction(func):
            return await func(*args, max_results=max_results)
        else:
            return await loop.run_in_executor(None, lambda: func(*args, max_results=max_results))
    except Exception as e:
        logger.error(f"❌ Error executing {scraper_key}: {e}")
        return [{"title": "search error", "url": "#", "price": str(e)}]


# Basic commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name or "Dear friend"
    welcome_text = (
        f"👋 Hello {user_name}!\n"
        "Welcome to the Scraper Shop bot 🛍️\n\n"
        "To learn how to use the bot, type the /help command."
    )
    await update.message.reply_text(welcome_text, reply_markup=start_keyboard())

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "ℹ️ About the bot:\n"
        "🤖 Name: Scraper Shop\n"
        "👤 Developer: Mohammad Sadegh Kordani and Ali Farisat\n"
        "📧 Support IDs: @AliZone, @Sadegh_kd \n\n"
        "🧭 How to use:\n"
        "1️⃣ Type the /shop command to see the websites.\n"
        "2️⃣ Choose the desired website.\n"
        "3️⃣ Write the name or link of the product and wait for the results! 🔎"
    )
    await update.message.reply_text(help_text, parse_mode='HTML', reply_markup=start_keyboard())

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🏪 Searchable Stores:\n"
        "1️⃣ Digikala\n"
        "2️⃣ eBay\n"
        "3️⃣ Global (link + name)\n\n"
        "Please choose one of the options 👇"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    removed_any = False

    for name, mgr in managers.items():
        try:
            removed = await mgr.cancel(chat_id)
            if removed:
                removed_any = True
        except Exception as e:
            logger.warning(f"⚠️ Error in cancel from manager {name}: {e}")

    if user_running.get(chat_id):
        user_running.pop(chat_id, None)
        removed_any = True

    if chat_id in user_state:
        user_state.pop(chat_id, None)

    if removed_any:
        await update.message.reply_text("✅ Operation canceled and removed from the queue if you were in it.", reply_markup=start_keyboard())
    else:
        await update.message.reply_text("ℹ️ No active operations found.", reply_markup=start_keyboard())


# مدیریت پیام‌ها
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    text = update.message.text.strip()
    state = user_state.get(chat_id)
    now = time.time()
    # Anti spam
    if chat_id in spam_blocked_users and now < spam_blocked_users[chat_id]:
        remaining = int(spam_blocked_users[chat_id] - now)
        await update.message.reply_text(f"⚠️ Please do not spam!\n⏳ {remaining} seconds remaining until the restriction is lifted.")
        return

    user_message_times.setdefault(chat_id, []).append(now)
    user_message_times[chat_id] = [t for t in user_message_times[chat_id] if now - t <= INTERVAL_SECONDS]
    if len(user_message_times[chat_id]) > MAX_MESSAGES:
        spam_blocked_users[chat_id] = now + BLOCK_DURATION
        await update.message.reply_text(f"🚫 Do not spam!\nThe bot will not respond for {BLOCK_DURATION} seconds.")
        return

    # General commands
    if text in ["ℹ️ Help", "/help"]:
        await help(update, context)
        return
    if text in ["🛒 Shops", "/shop"]:
        await shop(update, context)
        return
    if text == "❌ Cancel Operation":
        await cancel(update, context)
        return
    if text == "🔎 Digikala":
        user_state[chat_id] = {"mode": "digikala"}
        await update.message.reply_text("🛍️ Please send the product name to search on Digikala:")
        return
    if text == "🔎 eBay":
        user_state[chat_id] = {"mode": "ebay"}
        await update.message.reply_text("🌍 Please send the product name to search on eBay:")
        return
    if text == "🔎 Global (link + name)":
        user_state[chat_id] = {"mode": "global_link"}
        await update.message.reply_text("⚠️ In Global mode, errors may occur 🌐\n\n🔗 Please send the website link:")
        return

    if not state:
        await update.message.reply_text("Please select one of the options first.", reply_markup=start_keyboard())
        return

    mode = state.get("mode")

    # Digikala
    if mode == "digikala":
        if user_running.get(chat_id):
            await update.message.reply_text("⚠️ You currently have an active search. Please wait or press ❌ to cancel the operation.")
            return

        async def handler():
            start_time = time.time()
            try:
                await context.bot.send_chat_action(chat_id, "typing")
                await context.bot.send_message(chat_id, "⏳ Searching on Digikala ...")
                results = await call_scraper("digikala", query=text)
                duration = round(time.time() - start_time, 2)
                msg = format_results_html(results)
                await context.bot.send_message(chat_id, msg + f"\n\n⏱️ Search time: {duration} seconds", parse_mode='HTML')
            finally:
                user_running.pop(chat_id, None)
                user_state.pop(chat_id, None)

        user_running[chat_id] = True
        submit_res = await managers["digikala"].submit({"chat_id": chat_id, "handler_coroutine": handler})
        await update.message.reply_text(
            "✅ Search has started." if submit_res["status"] == "running"
            else f"⚙️ You are in the queue for Digikala (position {submit_res['position']})."
        )

    # eBay
    elif mode == "ebay":
        if user_running.get(chat_id):
            await update.message.reply_text("⚠️ You currently have an active search. Please wait or press ❌ to cancel the operation.")
            return

        async def handler():
            start_time = time.time()
            try:
                await context.bot.send_chat_action(chat_id, "typing")
                await context.bot.send_message(chat_id, "⏳ Searching on eBay ...")
                results = await call_scraper("ebay", query=text)
                duration = round(time.time() - start_time, 2)
                msg = format_results_html(results)
                await context.bot.send_message(chat_id, msg + f"\n\n⏱️ Search time: {duration} seconds", parse_mode='HTML')
            finally:
                user_running.pop(chat_id, None)
                user_state.pop(chat_id, None)

        user_running[chat_id] = True
        submit_res = await managers["ebay"].submit({"chat_id": chat_id, "handler_coroutine": handler})
        await update.message.reply_text(
            "✅ Search has started." if submit_res["status"] == "running"
            else f"⚙️ You are in the queue for eBay (position {submit_res['position']})."
        )

    # Global
    elif mode == "global_link":
        user_state[chat_id]["link"] = text
        user_state[chat_id]["mode"] = "global_name"
        await update.message.reply_text("📦 Now please send the product name:")
        return

    elif mode == "global_name":
        if user_running.get(chat_id):
            await update.message.reply_text("⚠️ You currently have an active search. Please wait or press ❌ to cancel the operation.")
            return

        link = user_state[chat_id].get("link")

        async def handler():
            start_time = time.time()
            try:
                await context.bot.send_chat_action(chat_id, "typing")
                await context.bot.send_message(chat_id, "⏳ Searching on Global ...")
                results = await call_scraper("global", query=text, link=link)
                duration = round(time.time() - start_time, 2)
                msg = format_results_html(results)
                await context.bot.send_message(chat_id, msg + f"\n\n⏱️ Search time: {duration} seconds", parse_mode='HTML')
            finally:
                user_running.pop(chat_id, None)
                user_state.pop(chat_id, None)

        user_running[chat_id] = True
        submit_res = await managers["global"].submit({"chat_id": chat_id, "handler_coroutine": handler})
        await update.message.reply_text(
            "✅ Search has started." if submit_res["status"] == "running"
            else f"⚙️ You are in the queue for Global (position {submit_res['position']})."
        )
def main():
    logger.info("🚀 Starting Telegram Scraper Bot ...")
    app = Application.builder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
