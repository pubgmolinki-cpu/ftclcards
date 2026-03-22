import asyncio
import random
import datetime
import sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- НАСТРОЙКИ ---
TOKEN = "8745143259:AAGndBWIy_9G8C4GjovoRA700trkveXNGNU"
ADMIN_ID = 1866813859 # Твой ID

bot = Bot(token=TOKEN)
dp = Dispatcher()

class GameState(StatesGroup):
    waiting_for_bet = State()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, 
                       last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, club TEXT, division TEXT, position TEXT, rarity TEXT, 
                       rarity_type TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards 
                      (user_id INTEGER, card_id INTEGER)''')
    conn.commit()
    conn.close()

def get_rarity_info(rating):
    if 50 <= rating < 75: return "Bronze 🥉", "bronze"
    elif 75 <= rating < 90: return "Gold 🥇", "gold"
    elif rating >= 90: return "Brilliant 💎", "brilliant"
    return "Common ⚪️", "common"

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Мини-Игры 🎲")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                   (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("Добро пожаловать в FTCL Cards! 🏆", reply_markup=main_menu())

@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    photo_id = message.photo[-1].file_id
    await message.reply(f"🆔 **ID Фотографии:**\n\n`{photo_id}`", parse_mode="Markdown")

# --- ПРОФИЛЬ ---
@dp.message(F.text == "Профиль 👤")
async def show_profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    
    if not user:
        await message.answer("Сначала напиши /start")
        return

    cards = cursor.execute("""SELECT all_cards.name, all_cards.rating, all_cards.position, all_cards.rarity 
                              FROM user_cards 
                              JOIN all_cards ON user_cards.card_id = all_cards.id 
                              WHERE user_id = ?""", (message.from_user.id,)).fetchall()
    
    card_list = "\n".join([f"• {c[0]} [{c[1]}] - {c[2]} ({c[3]})" for c in cards]) if cards else "Коллекция пуста"
    avg_rating = cursor.execute("SELECT AVG(rating) FROM user_cards JOIN all_cards ON user_cards.card_id = all_cards.id WHERE user_id = ?", (message.from_user.id,)).fetchone()[0] or 0
    
    text = (f"👤 **Игрок**: @{message.from_user.username}\n"
            f"💰 **Баланс**: {user[0]} 🌟\n"
            f"📊 **Ср. рейтинг**: {round(avg_rating, 1)}\n\n"
            f"🗂 **Твои карты**:\n{card_list}")
    await message.answer(text, parse_mode="Markdown")
    conn.close()

# --- ПОЛУЧИТЬ КАРТУ ---
@dp.message(F.text == "Получить Карту 🏆")
async def daily_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    
    user_row = cursor.execute("SELECT last_open FROM users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    
    if user_row is None:
        cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (message.from_user.id, message.from_user.username or "Player"))
        conn.commit()
        last_open_val = None
    else:
        last_open_val = user_row[0]

    now = datetime.datetime.now()

    if last_open_val:
        last_time = datetime.datetime.strptime(last_open_val, '%Y-%m-%d %H:%M:%S')
        if now < last_time + datetime.timedelta(hours=0):
            wait = (last_time + datetime.timedelta(hours=0)) - now
            await message.answer(f"⏳ Рано! Жди еще {wait.seconds // 1}ч. {(wait.seconds // 1) % 1}мин.")
            conn.close()
            return

    rand = random.randint(1, 100)
    if rand <= 65: r_type = "bronze"
    elif rand <= 95: r_type = "gold"
    else: r_type = "brilliant"

    card = cursor.execute("SELECT id, name, rating, stars, club, division, position, rarity, photo_id FROM all_cards WHERE rarity_type = ? ORDER BY RANDOM() LIMIT 1", (r_type,)).fetchone()
    
    if not card:
        card = cursor.execute("SELECT id, name, rating, stars, club, division, position, rarity, photo_id FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()

    if not card:
        await message.answer("⚠️ В базе нет игроков! Админ, добавь их.")
        conn.close()
        return

    cursor.execute("UPDATE users SET balance = balance + ?, last_open = ? WHERE user_id = ?", 
                   (card[3], now.strftime('%Y-%m-%d %H:%M:%S'), message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()

    caption = (f"🎊 **НОВАЯ КАРТА!**\n\n👤 **{card[1]}** | {card[7]}\n🏃 Позиция: {card[6]}\n📈 Рейтинг: {card[2]}\n🛡 Клуб: {card[4]}\n🏆 Дивизион: {card[5]}\n🌟 Награда: +{card[3]}")
    
    try:
        if card[8] and card[8] != "None":
            await message.answer_photo(photo=card[8], caption=caption, parse_mode="Markdown")
        else:
            await message.answer(caption, parse_mode="Markdown")
    except Exception as e:
        await message.answer(caption + f"\n\n*(Ошибка фото)*", parse_mode="Markdown")
    
    conn.close()

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "Мини-Игры 🎲")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Чет/Нечет 🎲", callback_data="game_even_odd")
    await message.answer("Выбери игру:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "game_even_odd")
async def start_dice(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ставку:")
    await state.set_state(GameState.waiting_for_bet)

@dp.message(GameState.waiting_for_bet)
async def process_bet(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введи число!")
        return
    bet = int(message.text)
    conn = sqlite3.connect("ftcl_cards.db")
    user = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    if not user or bet > user[0] or bet <= 0:
        await message.answer("Мало звезд!")
        conn.close()
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="Чётное", callback_data=f"dice_even_{bet}")
    kb.button(text="Нечётное", callback_data=f"dice_odd_{bet}")
    await message.answer(f"Ставка: {bet}🌟. Твой выбор:", reply_markup=kb.as_markup())
    await state.clear()
    conn.close()

@dp.callback_query(F.data.startswith("dice_"))
async def play_dice(callback: types.CallbackQuery):
    _, choice, bet = callback.data.split("_")
    bet = int(bet)
    dice_msg = await callback.message.answer_dice("🎲")
    win = (choice == "even" and dice_msg.dice.value % 2 == 0) or (choice == "odd" and dice_msg.dice.value % 2 != 0)
    
    conn = sqlite3.connect("ftcl_cards.db")
    if win:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bet, callback.from_user.id))
        await asyncio.sleep(3)
        await callback.message.answer(f"✅ Победа! +{bet}🌟")
    else:
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, callback.from_user.id))
        await asyncio.sleep(3)
        await callback.message.answer(f"❌ Проигрыш! -{bet}🌟")
    conn.commit()
    conn.close()

# --- МАГАЗИН ---
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze Pack (500🌟)", callback_data="buy_bronze")
    kb.button(text="Gold Pack (1500🌟)", callback_data="buy_gold")
    kb.button(text="Brilliant Pack (5000🌟)", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 Магазин паков:\n\n🥉 Bronze (50-74)\n🥇 Gold (75-89)\n💎 Brilliant (90-100)", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(callback: types.CallbackQuery):
    packs = {"bronze": (500, "bronze"), "gold": (1500, "gold"), "brilliant": (5000, "brilliant")}
    p_type = callback.data.split("_")[1]
    price, r_key = packs[p_type]

    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT balance FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    
    if not user or user[0] < price:
        await callback.answer("Мало звезд!", show_alert=True)
        return

    card = cursor.execute("SELECT id, name, rating, position FROM all_cards WHERE rarity_type = ? ORDER BY RANDOM() LIMIT 1", (r_key,)).fetchone()
    if not card:
        await callback.answer("В этом паке пока пусто!", show_alert=True)
        return

    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, callback.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (callback.from_user.id, card[0]))
    conn.commit()
    conn.close()
    await callback.message.answer(f"📦 Пак открыт! Выпал: {card[1]} [{card[2]}] - {card[3]}")

# --- АДМИНКА ---
@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.replace("/add_player ", "").split(", ")
        name, rating, stars, club, division, position, photo_id = parts
        r_label, r_key = get_rarity_info(int(rating))
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("INSERT INTO all_cards (name, rating, stars, club, division, position, rarity, rarity_type, photo_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                     (name, int(rating), int(stars), club, division, position, r_label, r_key, photo_id))
        conn.commit()
        await message.answer(f"✅ Игрок {name} добавлен!")
        conn.close()
    except:
        await message.answer("Ошибка! Формат:\n`/add_player Имя, Ретинг, Звезды, Клуб, Дивизион, Позиция, file_id`")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
