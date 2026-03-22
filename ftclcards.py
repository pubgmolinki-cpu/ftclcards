import asyncio
import random
import datetime
import sqlite3
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# Укажи свой токен в переменных окружения на Railway или замени здесь
TOKEN = os.getenv("8745143259:AAGndBWIy_9G8C4GjovoRA700trkveXNGNU")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    # Пользователи
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    # Все существующие карты в игре
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       position TEXT, rarity TEXT, photo_id TEXT)''')
    # Карты игрока
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    # Состав (11 позиций)
    cursor.execute('''CREATE TABLE IF NOT EXISTS lineup 
                      (user_id INTEGER PRIMARY KEY, 
                       gk INTEGER, 
                       def1 INTEGER, def2 INTEGER, def3 INTEGER, def4 INTEGER,
                       mid1 INTEGER, mid2 INTEGER, mid3 INTEGER, 
                       atk1 INTEGER, atk2 INTEGER, atk3 INTEGER)''')
    conn.commit()
    conn.close()

# --- КЛАВИАТУРЫ ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Стартовый Состав 🏟️")
    builder.button(text="Профиль 👤")
    builder.button(text="Мини-Игры 🎲")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                   (message.from_user.id, message.from_user.username or "Игрок"))
    # Создаем пустую запись в составе, если её нет
    cursor.execute("INSERT OR IGNORE INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("Добро пожаловать в FTCL Bot! 🏟️\nСобирай состав и готовься к матчам.", reply_markup=main_menu())

# ЛОГИКА СТАРТОВОГО СОСТАВА
@dp.message(F.text == "Стартовый Состав 🏟️")
async def show_lineup(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    
    # Получаем состав
    row = cursor.execute("SELECT * FROM lineup WHERE user_id = ?", (message.from_user.id,)).fetchone()
    
    # Если вдруг записи нет, создаем
    if not row:
        cursor.execute("INSERT INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
        conn.commit()
        row = [message.from_user.id] + [None]*11

    # Проверка заполненности линий
    gk = "✅" if row[1] else "❌"
    def_line = "✅" if all(row[2:6]) else "⚠️"
    mid_line = "✅" if all(row[6:9]) else "⚠️"
    atk_line = "✅" if all(row[9:12]) else "⚠️"

    text = (f"🏟 **Твой состав 4-3-3**\n\n"
            f"🧤 Вратарь (ВРТ): {gk}\n"
            f"🛡 Защита (ЗЩ): {def_line}\n"
            f"⚙️ Полузащита (ПЗ): {mid_line}\n"
            f"🔥 Атака (НП): {atk_line}\n\n"
            f"Нажми на кнопку ниже, чтобы выставить игрока в линию.")

    kb = InlineKeyboardBuilder()
    kb.button(text="🧤 Вратарь", callback_data="pick_Вратарь")
    kb.button(text="🛡 Защита", callback_data="pick_Защитник")
    kb.button(text="⚙️ Полузащита", callback_data="pick_Полузащитник")
    kb.button(text="🔥 Атака", callback_data="pick_Нападающий")
    kb.adjust(2)

    await message.answer(text, reply_markup=kb.as_markup())
    conn.close()

# ВЫБОР ИГРОКА ИЗ ИМЕЮЩИХСЯ
@dp.callback_query(F.data.startswith("pick_"))
async def list_players_for_lineup(callback: types.CallbackQuery):
    position_needed = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    conn = sqlite3.connect("ftcl_cards.db")
    # Ищем все карты пользователя с такой позицией
    cards = conn.execute("""
        SELECT all_cards.id, all_cards.name, all_cards.rating 
        FROM user_cards 
        JOIN all_cards ON user_cards.card_id = all_cards.id 
        WHERE user_cards.user_id = ? AND all_cards.position LIKE ?
    """, (user_id, f"%{position_needed}%")).fetchall()
    
    if not cards:
        await callback.answer(f"У тебя нет игроков на позицию {position_needed}!", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    for card_id, name, rating in cards:
        # callback_data: set_[позиция]_[card_id]
        kb.button(text=f"{name} ({rating})", callback_data=f"set_{position_needed}_{card_id}")
    
    kb.adjust(1)
    await callback.message.edit_text(f"Выбери игрока ({position_needed}):", reply_markup=kb.as_markup())
    conn.close()

# СОХРАНЕНИЕ В СОСТАВ
@dp.callback_query(F.data.startswith("set_"))
async def save_to_lineup(callback: types.CallbackQuery):
    _, pos, card_id = callback.data.split("_")
    user_id = callback.from_user.id
    
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    
    # Логика: находим первую свободную (или подходящую) ячейку в таблице lineup для этой позиции
    if pos == "Вратарь":
        cursor.execute("UPDATE lineup SET gk = ? WHERE user_id = ?", (card_id, user_id))
    elif pos == "Защитник":
        # Упрощенно: заполняем первую попавшуюся пустую из 4-х слотов защиты
        lineup = cursor.execute("SELECT def1, def2, def3, def4 FROM lineup WHERE user_id = ?", (user_id,)).fetchone()
        slot = "def1"
        if lineup[0] and not lineup[1]: slot = "def2"
        elif lineup[1] and not lineup[2]: slot = "def3"
        elif lineup[2] and not lineup[3]: slot = "def4"
        cursor.execute(f"UPDATE lineup SET {slot} = ? WHERE user_id = ?", (card_id, user_id))
    elif pos == "Полузащитник":
        lineup = cursor.execute("SELECT mid1, mid2, mid3 FROM lineup WHERE user_id = ?", (user_id,)).fetchone()
        slot = "mid1"
        if lineup[0] and not lineup[1]: slot = "mid2"
        elif lineup[1] and not lineup[2]: slot = "mid3"
        cursor.execute(f"UPDATE lineup SET {slot} = ? WHERE user_id = ?", (card_id, user_id))
    elif pos == "Нападающий":
        lineup = cursor.execute("SELECT atk1, atk2, atk3 FROM lineup WHERE user_id = ?", (user_id,)).fetchone()
        slot = "atk1"
        if lineup[0] and not lineup[1]: slot = "atk2"
        elif lineup[1] and not lineup[2]: slot = "atk3"
        cursor.execute(f"UPDATE lineup SET {slot} = ? WHERE user_id = ?", (card_id, user_id))

    conn.commit()
    conn.close()
    
    await callback.answer("Игрок добавлен в состав!")
    # Возвращаемся в меню состава
    await show_lineup(callback.message)

@dp.message(F.text == "Профиль 👤")
async def show_profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    user = conn.execute("SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = ?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    
    await message.answer(f"👤 **Профиль {message.from_user.first_name}**\n\n"
                         f"💰 Баланс: {user[0]} монет\n"
                         f" cards в коллекции: {count}")

async def main():
    init_db()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
