import telebot
from telebot import types
import os
import logging
import sqlite3
from datetime import datetime, timedelta
import random

# Пути
with open(os.path.join("..", "settings", "token.txt"), "r") as f:
    TOKEN = f.read().strip()

bot = telebot.TeleBot(TOKEN)

log_dir = os.path.join("..", "logs")
os.makedirs(log_dir, exist_ok=True)

console_log_path = os.path.join(log_dir, "console.log")
messages_log_path = os.path.join(log_dir, "messages.log")
db_path = os.path.join("..", "settings", "users.db")

active_blackjack_games = {}  # Активные игры

# Логирование
logging.basicConfig(
    filename=console_log_path,
    level=logging.INFO,
    format='%(asctime)s — %(levelname)s — %(message)s'
)

def log_message(message):
    with open(messages_log_path, "a", encoding="utf-8") as log_file:
        username = f"@{message.from_user.username}" if message.from_user.username else "без username"
        log_file.write(f"[{datetime.now()}] {message.from_user.first_name} ({username}) — {message.text}\n")

# --- База данных ---
def init_db():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            tokens INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            last_claim TEXT
        )
    """)
    for column in ["wins", "losses", "draws"]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()

# --- Вспомогательные функции ---
def get_user(user):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, username, first_name, tokens, wins, losses, draws, last_claim) VALUES (?, ?, ?, 0, 0, 0, 0, ?)",
                    (user.id, user.username, user.first_name, datetime.min.isoformat()))
        conn.commit()
    conn.close()

def update_tokens(user_id, amount):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE users SET tokens = tokens + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT tokens FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    return result[0] if result else 0

def update_last_claim(user_id, time_str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_claim = ? WHERE user_id = ?", (time_str, user_id))
    conn.commit()
    conn.close()

def update_stats(user_id, win=0, loss=0, draw=0):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE users SET wins = wins + ?, losses = losses + ?, draws = draws + ? WHERE user_id = ?",
                (win, loss, draw, user_id))
    conn.commit()
    conn.close()

def get_cooldown_remaining(user_id):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT last_claim FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    if result:
        last_time = datetime.fromisoformat(result[0])
        diff = timedelta(hours=6) - (datetime.now() - last_time)
        if diff.total_seconds() > 0:
            return str(diff).split(".")[0]
    return "00:00:00"

def can_claim(user_id):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT last_claim FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    if result:
        last_time = datetime.fromisoformat(result[0])
        return datetime.now() - last_time >= timedelta(hours=6)
    return True

def card_to_symbol(value):
    symbols = {
        2: '2️⃣', 3: '3️⃣', 4: '4️⃣', 5: '5️⃣', 6: '6️⃣',
        7: '7️⃣', 8: '8️⃣', 9: '9️⃣', 10: '🔟',
        11: '🂡'  # Туз
    }
    return symbols.get(value, str(value))

def format_hand(hand):
    return ' '.join([card_to_symbol(c) for c in hand]) + f"  (сумма: {sum(hand)})"

# --- Главное меню ---
def get_main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("💰 Получить токены", "🃏 Блэкджек")
    keyboard.row("📊 Баланс", "🏆 Топ игроков")
    return keyboard

@bot.message_handler(commands=['start'])
def handle_start(message):
    get_user(message.from_user)
    log_message(message)
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я игровой бот с токенами и мини-играми! Выбери действие ниже:",
        reply_markup=get_main_menu()
    )

@bot.message_handler(commands=['help'])
def handle_help(message):
    log_message(message)
    bot.send_message(
        message.chat.id,
        "/start — главное меню\n/help — помощь\n/top — топ игроков\n/balance — баланс токенов\n/blackjack — блэкджек"
    )

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT tokens, wins, losses, draws FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    if result:
        tokens, wins, losses, draws = result
        bot.send_message(message.chat.id, f"💰 Баланс: {tokens} токенов\n🏆 Победы: {wins}\n💀 Поражения: {losses}\n🤝 Ничьи: {draws}")

@bot.message_handler(commands=['top'])
def handle_top(message):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT first_name, username, tokens FROM users ORDER BY tokens DESC LIMIT 10")
    top = cur.fetchall()
    conn.close()
    msg = "🏆 Топ игроков по токенам:\n\n"
    for i, (name, username, tokens) in enumerate(top, 1):
        user_str = f"@{username}" if username else name
        msg += f"{i}. {user_str} — {tokens} токенов\n"
    bot.send_message(message.chat.id, msg)

@bot.message_handler(commands=['blackjack'])
def start_blackjack_game(message):
    get_user(message.from_user)
    user_id = message.from_user.id
    if user_id in active_blackjack_games:
        bot.send_message(message.chat.id, "🃏 Игра уже запущена. Введите ставку или завершите текущую.")
        return
    active_blackjack_games[user_id] = None
    bot.send_message(message.chat.id, "💵 Введите ставку для игры в Блэкджек:")

@bot.message_handler(func=lambda m: m.from_user.id in active_blackjack_games and active_blackjack_games[m.from_user.id] is None)
def handle_blackjack_bet(message):
    user_id = message.from_user.id
    try:
        bet = int(message.text)
        balance = get_balance(user_id)
        if bet <= 0:
            return bot.send_message(message.chat.id, "❌ Ставка должна быть положительной.")
        if bet > balance:
            return bot.send_message(message.chat.id, "❌ Недостаточно токенов для ставки.")

        player = [random.randint(2, 11), random.randint(2, 11)]
        dealer = [random.randint(2, 11)]

        active_blackjack_games[user_id] = {
            "bet": bet,
            "player": player,
            "dealer": dealer
        }

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("➕ Взять карту", "🛑 Стоп")

        bot.send_message(
            message.chat.id,
            f"┌───────────── БЛЭКДЖЕК ─────────────┐\n"
            f"│ 🂠 Ваша рука: {format_hand(player)}\n"
            f"│ 🂠 Карта дилера: {card_to_symbol(dealer[0])}\n"
            f"└──────────────────────────────────────┘",
            reply_markup=markup
        )

    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите целое число для ставки.")

@bot.message_handler(func=lambda m: m.text in ["➕ Взять карту", "🛑 Стоп"])
def handle_blackjack_action(message):
    user_id = message.from_user.id
    game = active_blackjack_games.get(user_id)
    if not game:
        return bot.send_message(message.chat.id, "❌ У вас нет активной игры.")

    if message.text == "➕ Взять карту":
        game["player"].append(random.randint(2, 11))
        total = sum(game["player"])
        if total > 21:
            update_tokens(user_id, -game["bet"])
            update_stats(user_id, loss=1)
            del active_blackjack_games[user_id]
            return bot.send_message(
                message.chat.id,
                f"┌─────── ИТОГ 🃏 ───────┐\n"
                f"│ 💥 Перебор! Ваша сумма: {total}\n│ Вы проиграли 💸\n"
                f"└──────────────────────┘",
                reply_markup=get_main_menu()
            )
        else:
            return bot.send_message(
                message.chat.id,
                f"🂠 Ваша рука: {format_hand(game['player'])}"
            )

    elif message.text == "🛑 Стоп":
        while sum(game["dealer"]) < 17:
            game["dealer"].append(random.randint(2, 11))

        player_sum = sum(game["player"])
        dealer_sum = sum(game["dealer"])

        text = "┌─────── ИТОГ 🃏 ───────┐\n"
        text += f"│ 🂠 Ваша рука: {format_hand(game['player'])}\n"
        text += f"│ 🤖 Рука дилера: {format_hand(game['dealer'])}\n"

        if dealer_sum > 21 or player_sum > dealer_sum:
            update_tokens(user_id, game["bet"])
            update_stats(user_id, win=1)
            text += "│ 🎉 Вы выиграли!"
        elif player_sum < dealer_sum:
            update_tokens(user_id, -game["bet"])
            update_stats(user_id, loss=1)
            text += "│ 💸 Вы проиграли."
        else:
            update_stats(user_id, draw=1)
            text += "│ 🤝 Ничья. Ставка возвращена."

        text += "\n└──────────────────────┘"
        del active_blackjack_games[user_id]
        bot.send_message(message.chat.id, text, reply_markup=get_main_menu())


@bot.message_handler(func=lambda m: m.text in ["➕ Взять карту", "🛑 Стоп"])
def handle_blackjack_action(message):
    user_id = message.from_user.id
    game = active_blackjack_games.get(user_id)
    if not game:
        return bot.send_message(message.chat.id, "❌ У вас нет активной игры.")

    if message.text == "➕ Взять карту":
        game["player"].append(random.randint(2, 11))
        total = sum(game["player"])
        if total > 21:
            update_tokens(user_id, -game["bet"])
            update_stats(user_id, loss=1)
            del active_blackjack_games[user_id]
            return bot.send_message(message.chat.id, f"💥 Перебор! Ваша сумма: {total}\nВы проиграли 💸")
        else:
            return bot.send_message(message.chat.id, f"🂠 Ваша рука: {game['player']} (сумма: {total})")

    elif message.text == "🛑 Стоп":
        while sum(game["dealer"]) < 17:
            game["dealer"].append(random.randint(2, 11))

        player_sum = sum(game["player"])
        dealer_sum = sum(game["dealer"])
        text = f"🂠 Ваша рука: {game['player']} (сумма: {player_sum})\n"
        text += f"🂠 Рука дилера: {game['dealer']} (сумма: {dealer_sum})\n\n"

        if dealer_sum > 21 or player_sum > dealer_sum:
            update_tokens(user_id, game["bet"])
            update_stats(user_id, win=1)
            text += "🎉 Вы выиграли!"
        elif player_sum < dealer_sum:
            update_tokens(user_id, -game["bet"])
            update_stats(user_id, loss=1)
            text += "💸 Вы проиграли."
        else:
            update_stats(user_id, draw=1)
            text += "🤝 Ничья. Ставка возвращена."

        del active_blackjack_games[user_id]
        bot.send_message(message.chat.id, text, reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "💰 Получить токены")
def claim_tokens(message):
    user_id = message.from_user.id
    get_user(message.from_user)
    if can_claim(user_id):
        update_tokens(user_id, 500)
        update_last_claim(user_id, datetime.now().isoformat())
        bot.send_message(message.chat.id, "🎉 Вы получили 500 токенов!")
    else:
        remaining = get_cooldown_remaining(user_id)
        bot.send_message(message.chat.id, f"⌛️ Получить токены можно через: {remaining}")

@bot.message_handler(func=lambda m: m.text == "📊 Баланс")
def show_balance(message):
    handle_balance(message)

@bot.message_handler(func=lambda m: m.text == "🏆 Топ игроков")
def show_top(message):
    handle_top(message)

@bot.message_handler(func=lambda m: m.text == "🃏 Блэкджек")
def blackjack_entry(message):
    start_blackjack_game(message)

if __name__ == "__main__":
    init_db()
    logging.info("Бот запущен")
    bot.polling(none_stop=True)