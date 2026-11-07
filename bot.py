import logging
import os
import asyncio

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("trigger-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])  # твой telegram user id

# --- состояние в памяти (слетает при рестарте, так и задумано) ---
STATE_IDLE = "idle"           # ждём /start от владельца
STATE_WAIT_TRIGGER = "wait_trigger"   # ждём слово-триггер
STATE_WAIT_TEXT = "wait_text"         # ждём текст ответа
STATE_ARMED = "armed"         # слушаем всех, ищем точное совпадение
STATE_DONE = "done"           # уже сработало, больше не реагируем

state = {
    "status": STATE_IDLE,
    "trigger": None,
    "text": None,
}
lock = asyncio.Lock()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type != ChatType.PRIVATE:
        return  # в группах/чате поддержки бот вообще молчит

    if user.id != OWNER_ID:
        return  # посторонним на /start бот не отвечает и не настраивается

    async with lock:
        state["status"] = STATE_WAIT_TRIGGER
        state["trigger"] = None
        state["text"] = None

    await update.message.reply_text(
        "Готов. Напиши слово-триггер (следующим сообщением)."
    )


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    text = update.message.text

    if chat.type != ChatType.PRIVATE:
        return  # только личные сообщения, групповые/чат поддержки игнорируем всегда

    # --- ветка владельца: настройка триггера и текста ---
    if user.id == OWNER_ID:
        async with lock:
            status = state["status"]

            if status == STATE_WAIT_TRIGGER:
                state["trigger"] = text.strip()
                state["status"] = STATE_WAIT_TEXT
                await update.message.reply_text(
                    "Триггер записан. Теперь пришли текст, который бот отправит "
                    "первому написавшему это слово."
                )
                return

            if status == STATE_WAIT_TEXT:
                state["text"] = text
                state["status"] = STATE_ARMED
                await update.message.reply_text(
                    f"Готово. Жду, кто первым напишет боту в личку слово: "
                    f"«{state['trigger']}»."
                )
                return

        # если владелец пишет что-то вне этих двух шагов — игнор
        return

    # --- ветка постороннего пользователя ---
    async with lock:
        if state["status"] != STATE_ARMED:
            return  # бот ещё не настроен, либо уже сработал — молчим

        if text.strip() != state["trigger"]:
            return  # не то слово — вообще никак не реагируем

        # первое совпадение — забираем текст и сразу гасим стейт,
        # чтобы второй одновременный апдейт не прошёл тоже
        response_text = state["text"]
        state["status"] = STATE_DONE

    await context.bot.send_message(chat_id=chat.id, text=response_text)
    log.info("Trigger fired for user_id=%s chat_id=%s", user.id, chat.id)

    # разовая настройка: после срабатывания процесс останавливается,
    # рестарт — вручную (на Render: Manual Deploy / Restart)
    context.application.create_task(_shutdown(context.application))


async def _shutdown(app: Application):
    await asyncio.sleep(0.5)  # дать апдейту долистать до конца
    os._exit(0)  # жёсткий выход, без ожидания graceful-стопа


async def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_private_text)
    )

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
    )

    log.info("bot started, owner_id=%s", OWNER_ID)

    # держим процесс живым вечно; реальный выход — os._exit(0) из _shutdown()
    await asyncio.Event().wait()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
