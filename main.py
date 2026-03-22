import asyncio
import random
import datetime
import sqlite3
import os
import html # Стандартная библиотека для защиты текста
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859 # <--- ЗАМЕНИ НА СВОЙ ID

# Используем HTML, так как он стабильнее при наличии спецсимволов
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    # Создаем таблицы без лишних колонок (без wins)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, club TEXT, rarity_type TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    conn.commit()
    conn.close()

def get_random_card(rarity=None):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    if not rarity:
        rand = random.randint(1, 100)
        if rand <= 75: rarity = "bronze"
        elif rand <= 95: rarity = "gold"
        else: rarity = "brilliant"
    
    # Поиск по rarity_type (маленькими буквами, как в твоей базе)
    search_rarity = rarity.lower()
    card = cursor.execute(
        "SELECT * FROM all_cards WHERE LOWER(TRIM(rarity_type)) = ? ORDER BY RANDOM() LIMIT 1", 
        (search_rarity,)
    ).fetchone()
    conn.close()
    return card

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("⚽️ FTCL Cards: Исправленная версия запущена!", reply_markup=main_menu())

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message(F.text == "Получить Карту 🏆")
async def daily_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT last_open FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    now = datetime.datetime.now()
    
    if user and user[0]:
        last = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S')
        if now < last + datetime.timedelta(hours=0):
            rem = (last + datetime.timedelta(hours=0)) - now
            await message.answer(f"⏳ Доступно через {rem.seconds //             await message.answer(f"⏳ Доступно через {rem.seconds60}мин.")
            return

    card = get_random_card()
    if not card:
        await message.answer("⚠️ Игроков нет в базе!")
        return

    status_msg = await message.answer("📦 Распаковка...")
    await asyncio.sleep(1)
    await status_msg.delete()

    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()
    
    emoji = {"bronze": "🥉", "gold": "🥇", "brilliant": "💎"}
    # Экранируем спецсимволы через html.escape
    text = (f"<b>🎊 Твоя карта!</b>\n\n👤 {html.escape(card[1])}\n📈 Рейтинг: {card[2]}\n🛡 Клуб: {html.escape(card[4])}\n"
            f"✨ Тип: {card[5].capitalize()} {emoji.get(card[5].lower(), '')}")
    
    try:
        await message.answer_photo(photo=card[6], caption=text)
    except:
        await message.answer(text)

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze Pack (500🌟)", callback_data="buy_Bronze")
    kb.button(text="Gold Pack (1500🌟)", callback_data="buy_Gold")
    kb.button(text="Brilliant Pack (5000🌟)", callback_data="buy_Brilliant")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин FTCL</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(cb: types.CallbackQuery):
    rarity = cb.data.split("_")[1]
    prices = {"Bronze": 500, "Gold": 1500, "Brilliant": 5000}
    
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (cb.from_user.id,)).fetchone()
    
    if not u or u[0] < prices[rarity]:
        await cb.answer("Недостаточно звезд!", show_alert=True)
        conn.close()
        return

    card = get_random_card(rarity)
    if not card:
        await cb.answer(f"Игроков {rarity} нет!", show_alert=True)
        conn.close()
        return

    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (prices[rarity], cb.from_user.id))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (cb.from_user.id, card[0]))
    conn.commit()
    conn.close()

    await cb.answer()
    status = await cb.message.answer(f"📦 Открываем {rarity} пак...")
    await asyncio.sleep(1.2)
    await status.delete()

    emoji = {"bronze": "🥉", "gold": "🥇", "brilliant": "💎"}
    text = (f"🌟 <b>Пак открыт!</b>\n\n👤 {html.escape(card[1])}\n📈 Рейтинг: {card[2]}\n"
            f"🛡 Клуб: {html.escape(card[4])}\n✨ Редкость: {card[5].capitalize()} {emoji.get(card[5].lower(), '')}")

    try:
        if card[6] and str(card[6]) != "None":
            await cb.message.answer_photo(photo=card[6], caption=text)
        else:
            await cb.message.answer(text)
    except Exception as e:
        await cb.message.answer(text + f"\n\n⚠️ Ошибка фото: {e}")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    # Профиль без колонки wins, чтобы не было ошибки sqlite3.OperationalError
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.answer(f"👤 <b>@{message.from_user.username}</b>\n💰 Баланс: {u[0]}🌟\n🗂 Коллекция: {c} шт.")

async def main():
    init_db()
    # Сброс вебхука при старте решает проблему TelegramConflictError
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
