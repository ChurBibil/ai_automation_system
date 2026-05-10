import os
from dotenv import load_dotenv

load_dotenv() # Загружает переменные из файла .env
TOKEN = os.getenv("BOT_TOKEN")
import telebot
from telebot import types
import sqlite3
import threading
import time
import pytz
import dateparser
import html
from datetime import datetime

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
msk_tz = pytz.timezone('Europe/Moscow')

db_lock = threading.Lock()
last_briefing_date = None

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('tasks.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tasks
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task TEXT, due_date TEXT, is_routine_instance INTEGER, status TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS routines
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task TEXT)''')
    conn.commit()
    return conn, cursor

conn, cursor = init_db()

# --- КНОПКИ МЕНЮ ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("📋 Мои дела"), types.KeyboardButton("🔄 Добавить рутину"))
    return markup

# --- КОМАНДА СТАРТ ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    text = "О, какие люди. Ну здорово, фраерок! Буду пинать тебя, чтоб ты дела делал, а то расслабился совсем... \n\n<b>Как ставить задачи:</b>\nПиши дело и время <b>через запятую</b>. Например:\n<i>Купить шаурму, завтра в 18:00</i>\n<i>Позвонить мамке, в 20:30</i>\n\nЕсли времени нет, просто пиши дело без запятой."
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="HTML")

# --- ДОБАВЛЕНИЕ РУТИНЫ ---
@bot.message_handler(func=lambda m: m.text == "🔄 Добавить рутину")
def add_routine_start(message):
    bot.send_message(message.chat.id, "Че за ежедневная рутина? Давай, пиши текстом, что ты там собрался делать каждый день. Только без времени, просто суть.")
    bot.register_next_step_handler(message, save_routine)

def save_routine(message):
    if message.text in ["📋 Мои дела", "🔄 Добавить рутину"]:
        bot.send_message(message.chat.id, "Эй, не ломай мне кнопки. Жми нормально или пиши текст.")
        return

    with db_lock:
        cursor.execute("INSERT INTO routines (user_id, task) VALUES (?, ?)", (message.chat.id, message.text))
        cursor.execute("INSERT INTO tasks (user_id, task, due_date, is_routine_instance, status) VALUES (?, ?, ?, ?, ?)", (message.chat.id, message.text, "", 1, "active"))
        conn.commit()

    bot.send_message(message.chat.id, f"Понял. Добавил <b>'{html.escape(message.text)}'</b> в список твоих ежедневных страданий. Каждое утро в 8:00 по МСК будет в твоей сводке.", parse_mode="HTML")

# --- СПИСОК ДЕЛ ---
@bot.message_handler(func=lambda m: m.text == "📋 Мои дела")
def show_tasks(message):
    update_task_list_message(message.chat.id)

def update_task_list_message(chat_id, message_id=None):
    with db_lock:
        cursor.execute("SELECT id, task, due_date FROM tasks WHERE user_id=? AND status='active'", (chat_id,))
        tasks = cursor.fetchall()

    if not tasks:
        text = "🎉 Ого! Дел нет (или ты всё сделал). Уважаю, братик! Можешь дальше деградировать на диване. 🛋"
        if message_id:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML")
        else:
            bot.send_message(chat_id, text, parse_mode="HTML")
        return

    text = "📝 <b>Список твоих мучений:</b>\n\n"
    markup = types.InlineKeyboardMarkup()

    for t in tasks:
        t_id, t_text, t_due = t
        row_text = f"[{t_due.split()[1]}] {t_text}" if t_due else t_text
        text += f"• {row_text}\n"
        markup.add(types.InlineKeyboardButton(text=f"✅ {t_text[:30]}", callback_data=f"done_{t_id}"))

    if message_id:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

# --- ДОБАВЛЕНИЕ ЗАДАЧИ ---
@bot.message_handler(content_types=['text'])
def add_task(message):
    if "," in message.text:
        parts = message.text.rsplit(",", 1)
        task_text, time_str = parts[0].strip(), parts[1].strip()

        dt = dateparser.parse(time_str, languages=['ru'], settings={'TIMEZONE': 'Europe/Moscow', 'RETURN_AS_TIMEZONE_AWARE': True, 'PREFER_DATES_FROM': 'future'})

        if dt:
            db_date = dt.strftime("%Y-%m-%d %H:%M")
            with db_lock:
                cursor.execute("INSERT INTO tasks (user_id, task, due_date, is_routine_instance, status) VALUES (?, ?, ?, ?, ?)", (message.chat.id, task_text, db_date, 0, "active"))
                conn.commit()
            bot.reply_to(message, f"Ага, записал: <b>{html.escape(task_text)}</b>.\nЖду исполнения до {db_date}. Смотри не слейся, ленивая жопа! 🕒", parse_mode="HTML")
        else:
            bot.reply_to(message, "Э, братик, я не понял твой эльфийский. Пиши время нормально: 'через час', 'завтра в 15:00'.")
    else:
        with db_lock:
            cursor.execute("INSERT INTO tasks (user_id, task, due_date, is_routine_instance, status) VALUES (?, ?, ?, ?, ?)", (message.chat.id, message.text, "", 0, "active"))
            conn.commit()
        bot.reply_to(message, f"Закинул <b>{html.escape(message.text)}</b> в список. Времени нет, так что сделай как-нибудь, как руки дойдут. 🤷‍♂️", parse_mode="HTML")

# --- НАЖАТИЕ КНОПКИ "СДЕЛАНО" ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('done_'))
def mark_as_done(call):
    task_id = call.data.split('_')[1]

    with db_lock:
        cursor.execute("UPDATE tasks SET status='done' WHERE id=?", (task_id,))
        conn.commit()

    bot.answer_callback_query(call.id, "Опа, красава! Вычеркиваю.")

    if "Список твоих мучений" in call.message.text:
        update_task_list_message(call.message.chat.id, call.message.message_id)
    else:
        safe_text = html.escape(call.message.text)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"<s>{safe_text}</s>\n\n✅ <b>Сделано. Мужик!</b>", parse_mode="HTML")

# --- ФОНОВЫЙ ПРОЦЕСС ---
def background_worker():
    global last_briefing_date
    while True:
        try:
            now = datetime.now(msk_tz)
            now_str = now.strftime("%Y-%m-%d %H:%M")

            with db_lock:
                cursor.execute("SELECT id, user_id, task FROM tasks WHERE status='active' AND is_routine_instance=0 AND due_date=?", (now_str,))
                for r in cursor.fetchall():
                    task_id, user_id, task_text = r
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton(text="✅ Сделано", callback_data=f"done_{task_id}"))
                    bot.send_message(user_id, f"🚨 Эй! Время пришло! Пора делать: <b>{html.escape(task_text)}</b>. Подрывайся давай!", parse_mode="HTML", reply_markup=markup)
                    cursor.execute("UPDATE tasks SET status='notified' WHERE id=?", (task_id,))
                conn.commit()

                if now.hour == 8 and now.minute == 0 and last_briefing_date != now.date():
                    last_briefing_date = now.date()
                    cursor.execute("UPDATE tasks SET status='missed' WHERE is_routine_instance=1 AND status='active'")

                    cursor.execute("SELECT DISTINCT user_id FROM routines")
                    for u in cursor.fetchall():
                        uid = u[0]
                        cursor.execute("SELECT task FROM routines WHERE user_id=?", (uid,))
                        for r in cursor.fetchall():
                            cursor.execute("INSERT INTO tasks (user_id, task, due_date, is_routine_instance, status) VALUES (?, ?, ?, ?, ?)", (uid, r[0], "", 1, "active"))
                    conn.commit()

                    users = set([u[0] for u in cursor.execute("SELECT DISTINCT user_id FROM tasks").fetchall()] +
                                [u[0] for u in cursor.execute("SELECT DISTINCT user_id FROM routines").fetchall()])

                    for uid in users:
                        cursor.execute("SELECT task FROM tasks WHERE user_id=? AND is_routine_instance=1 AND status='active'", (uid,))
                        routines = cursor.fetchall()
                        today_prefix = now.strftime("%Y-%m-%d") + "%"
                        cursor.execute("SELECT task, due_date FROM tasks WHERE user_id=? AND is_routine_instance=0 AND status='active' AND due_date LIKE ?", (uid, today_prefix))
                        today_tasks = cursor.fetchall()

                        msg = "☀️ <b>Здарова, соня! Подъем.</b> Вот твои планы на сегодня, если ты не решил проваляться на диване весь день:\n\n"
                        has_tasks = False

                        if routines:
                            msg += "🔄 <b>Твоя рутина (обязаловка):</b>\n"
                            for r in routines: msg += f"— {r[0]}\n"
                            msg += "\n"
                            has_tasks = True

                        if today_tasks:
                            msg += "📌 <b>Разовые дела:</b>\n"
                            for t in today_tasks: msg += f"— {t[0]} (в {t[1].split()[1]})\n"
                            has_tasks = True

                        if not has_tasks:
                            msg += "А дел-то на сегодня нет! Иди пинай балду. 🛋"

                        bot.send_message(uid, msg, parse_mode="HTML")

        except Exception as e:
            print("Ошибка фонового процесса:", e)

        time.sleep(60)

# --- ЗАПУСК ---
threading.Thread(target=background_worker, daemon=True).start()
print("Братский бот запущен!")
bot.infinity_polling()