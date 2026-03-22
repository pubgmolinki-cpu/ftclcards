import asyncio
import random
import datetime
import sqlite3
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")  # Проверь, что в Railway это капсом!
ADMIN_ID = 1866813859        # Твой ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()

class GameStates(StatesGroup):
    waiting_for_bet = State()
    waiting_for_opponent = State()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, 
                       last_open TEXT, wins INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, club TEXT, division TEXT, position TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS lineup 
                      (user_id INTEGER PRIMARY KEY, gk INTEGER, def1 INTEGER, def2 INTEGER, def3 INTEGER, def4 INTEGER,
                       mid1 INTEGER, mid2 INTEGER, mid3 INTEGER, atk1 INTEGER, atk2 INTEGER, atk3 INTEGER)''')
    conn.commit()
    conn.close()

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Стартовый Состав 🏟️")
    builder.button(text="Поиск соперника ⚔️")
    builder.button(text="Профиль 👤")
    builder.button(text="Мини-Игры 🎲")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- МАТЧИ И ПОИСК ---

@dp.message(F.text == "Поиск соперника ⚔️")
async def match_search(message: types.Message, state: FSMContext):
    await message.answer("Введите @username пользователя, которого хотите вызвать на матч:")
    await state.set_state(GameStates.waiting_for_opponent)

@dp.message(GameStates.waiting_for_opponent)
async def invite_sent(message: types.Message, state: FSMContext):
    target_username = message.text.replace("@", "")
    conn = sqlite3.connect("ftcl_cards.db")
    opponent = conn.execute("SELECT user_id FROM users WHERE username = ?", (target_username,)).fetchone()
    
    if not opponent:
        await message.answer("Пользователь не найден в базе бота.")
        await state.clear()
        return

    # Проверка состава у вызывающего
    my_lineup = conn.execute("SELECT gk, atk3 FROM lineup WHERE user_id = ?", (message.from_user.id,)).fetchone()
    if not my_lineup or None in my_lineup:
        await message.answer("Сначала собери полный состав (11 игроков)!")
        await state.clear()
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="Принять вызов ✅", callback_data=f"accept_{message.from_user.id}")
    kb.button(text="Отклонить ❌", callback_data="decline_match")
    
    try:
        await bot.send_message(opponent[0], f"⚠️ Вас вызывает на матч @{message.from_user.username}!", reply_markup=kb.as_markup())
        await message.answer("Приглашение отправлено!")
    except:
        await message.answer("Не удалось отправить сообщение (возможно, бот заблокирован).")
    
    await state.clear()
    conn.close()

@dp.callback_query(F.data.startswith("accept_"))
async def play_match(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[1])
    defender_id = callback.from_user.id
    
    conn = sqlite3.connect("ftcl_cards.db")
    def get_avg_rating(uid):
        res = conn.execute("""SELECT AVG(rating) FROM lineup 
                              JOIN all_cards ON (lineup.gk = all_cards.id OR lineup.def1 = all_cards.id OR lineup.atk3 = all_cards.id) 
                              WHERE user_id = ?""", (uid,)).fetchone()
        return res[0] or 0

    rate1 = get_avg_rating(challenger_id)
    rate2 = get_avg_rating(defender_id)

    if rate1 > rate2 + random.randint(-5, 5):
        winner_id, winner_name = challenger_id, "Вызывающий"
    else:
        winner_id, winner_name = defender_id, callback.from_user.username

    conn.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (winner_id,))
    conn.commit()
    conn.close()

    result_text = f"🏟 Матч окончен!\nПобедитель: @{winner_name}\n\nСредний рейтинг:\nВы: {round(rate2,1)}\nСоперник: {round(rate1,1)}"
    await callback.message.answer(result_text)
    await bot.send_message(challenger_id, result_text)

# --- МАГАЗИН И ИГРЫ (ИСПРАВЛЕНО) ---

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Пак Новичка (500🌟)", callback_data="buy_pack")
    await message.answer("🛒 Магазин паков:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "buy_pack")
async def buy(callback: types.CallbackQuery):
    conn = sqlite3.connect("ftcl_cards.db")
    user = conn.execute("SELECT balance FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if user[0] < 500:
        await callback.answer("Недостаточно звезд!", show_alert=True)
        return
    
    card = conn.execute("SELECT id, name FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    if not card:
        await callback.answer("В магазине пока пусто!", show_alert=True)
        return

    conn.execute("UPDATE users SET balance = balance - 500 WHERE user_id = ?", (callback.from_user.id,))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (callback.from_user.id, card[0]))
    conn.commit()
    conn.close()
    await callback.message.answer(f"📦 Вы купили игрока: {card[1]}")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance, wins FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    await message.answer(f"👤 Профиль: @{message.from_user.username}\n💰 Баланс: {u[0]}🌟\n🏆 Побед: {u[1]}\n🗂 Карт: {c}")

# --- ОСТАЛЬНОЕ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("FTCL Bot готов к работе!", reply_markup=main_menu())

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
