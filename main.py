import os
import json
import logging
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "owner_id": None,
        "trigger": "",
        "response": "",
        "has_replied": False,
        "setup_state": "idle"
    }

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# --- ФОНОВЫЙ HTTP-СЕРВЕР ДЛЯ RENDER.COM ---
def run_dummy_server():
    port = int(os.getenv("PORT", 8080))
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Telegram Bot Web Service is running")
        def log_message(self, format, *args):
            pass # Отключаем спам в логах от проверок здоровья Render
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    logging.info(f"✅ Web-сервер запущен на порту {port} (требование Render)")
    server.serve_forever()

# Используем F.chat.type == ChatType.PRIVATE вместо устаревшего ChatTypeFilter
@dp.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: types.Message):
    config = load_config()
    
    if config["owner_id"] is None:
        config["owner_id"] = message.from_user.id
        config["setup_state"] = "waiting_trigger"
        save_config(config)
        await message.answer("✅ Режим настройки активирован.\n\nНапиши слово-триггер, на которое бот должен реагировать:")
    elif message.from_user.id == config["owner_id"]:
        config["setup_state"] = "waiting_trigger"
        config["has_replied"] = False
        config["trigger"] = ""
        config["response"] = ""
        save_config(config)
        await message.answer("🔄 Настройки сброшены. Введи новое слово-триггер:")

@dp.message(F.chat.type == ChatType.PRIVATE)
async def handle_message(message: types.Message):
    # Игнорируем команды в процессе настройки, чтобы не ломать логику
    if message.text and message.text.startswith("/"):
        return
    
    config = load_config()

    # --- ЛОГИКА ДЛЯ ВЛАДЕЛЬЦА ---
    if message.from_user.id == config["owner_id"]:
        if config["setup_state"] == "waiting_trigger":
            config["trigger"] = message.text
            config["setup_state"] = "waiting_response"
            save_config(config)
            await message.answer("✅ Триггер сохранен.\n\nТеперь напиши текст, который бот отправит в ответ:")
        elif config["setup_state"] == "waiting_response":
            config["response"] = message.text
            config["setup_state"] = "armed"
            save_config(config)
            await message.answer("🚀 Бот готов к работе!\n\nОн ответит только первому, кто напишет триггер, и навсегда замолчит.")
        elif config["setup_state"] == "armed":
            await message.answer(f"⚙️ Бот уже настроен и ждет.\nТриггер: `{config['trigger']}`\n\nНапиши /start, чтобы перенастроить.")
        return

    # --- ЛОГИКА ДЛЯ ПОСТОРОННИХ (ТОЛЬКО ЛС) ---
    if config["setup_state"] == "armed" and not config["has_replied"]:
        if message.text and message.text.strip().lower() == config["trigger"].strip().lower():
            try:
                await message.answer(config["response"])
                config["has_replied"] = True
                save_config(config)
                
                await bot.send_message(
                    config["owner_id"], 
                    "✅ УСПЕХ! Бот отправил текст первому пользователю. Теперь он игнорирует всех."
                )
            except Exception as e:
                logging.error(f"Ошибка отправки: {e}")

async def main():
    # Запускаем фиктивный веб-сервер в фоновом потоке, чтобы удовлетворить требование Render Web Service
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()
    
    # Запускаем бота
    logging.info("🤖 Запуск бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
