import asyncio, psycopg2, os, random, time, logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from psycopg2.extras import DictCursor

# --- ЛОГИ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

# --- КОНФИГ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859)) 
CHANNELS = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"]

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Состояния
cooldowns, active_matches, guessing_game = {}, {}, {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def send_admin_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def check_sub(uid):
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

# --- СТАРТ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid, uname = message.from_user.id, message.from_user.username
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, uname))
    conn.commit(); cur.close(); conn.close()
    await send_admin_log(f"🆕 Новый юзер: @{uname}")
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards запущен!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОШАГОВЫЙ ПАК-ОПЕНИНГ ---
@dp.message(F.text == "Получить Карту 🏆")
async def pack_open(message: types.Message):
    uid = message.from_user.id
    if not await check_sub(uid): return await message.answer("❌ Подпишись на каналы!")
    
    now = time.time()
    if uid in cooldowns and now - cooldowns[uid] < 14400:
        rem = int(14400 - (now - cooldowns[uid]))
        return await message.answer(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}м.")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    
    status = await message.answer("Открываем пак... 💼")
    await asyncio.sleep(2)
    await status.edit_text(f"Позиция: <b>{card['position']}</b>")
    await asyncio.sleep(2)
    await status.edit_text(f"Позиция: <b>{card['position']}</b>\nКлуб: <b>{card['club']}</b>")
    await asyncio.sleep(2)
    await status.edit_text(f"Позиция: <b>{card['position']}</b>\nКлуб: <b>{card['club']}</b>\nРейтинг: <b>{card['rating']}</b>")
    await asyncio.sleep(1); await status.delete()

    cooldowns[uid] = now
    cur.execute("UPDATE users SET balance = balance + 1000 WHERE user_id = %s", (uid,))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()
    
    await send_admin_log(f"👤 @{message.from_user.username} выбил {card['name']}")
    await message.answer_photo(card['photo_id'], caption=f"🎉 <b>{card['name'].upper()}</b>\n📊 {card['rating']}\n🛡 {card['club']}")

# --- МИНИ-ИГРЫ (ВСЕ 3 ИГРЫ) ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти", callback_data="game_pnl")
    kb.button(text="🧩 Угадай игрока", callback_data="game_guess")
    kb.button(text="⚔️ PvP Матч (Инфо)", callback_data="pvp_info")
    await message.answer("🎯 <b>Игровой зал:</b>", reply_markup=kb.adjust(1).as_markup())

# 1. Пенальти
@dp.callback_query(F.data == "game_pnl")
async def pnl_start(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for pos in ["Лево ⬅️", "Центр ⬆️", "Право ➡️"]: kb.button(text=pos, callback_data="pnl_kick")
    await call.message.edit_text("🥅 Бей пенальти!", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "pnl_kick")
async def pnl_kick(call: types.CallbackQuery):
    win = random.choice([True, False])
    reward = 500 if win else 0
    if win:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, call.from_user.id))
        conn.commit(); cur.close(); conn.close()
    await call.message.edit_text("✅ ГОЛ! +500 ⭐" if win else "❌ МИМО!")

# 2. Угадайка
@dp.callback_query(F.data == "game_guess")
async def guess_start(call: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    guessing_game[call.from_user.id] = card['name'].lower()
    await call.message.edit_text(f"🧩 <b>Угадай игрока по клубу и рейтингу!</b>\n\n🛡 Клуб: {card['club']}\n📊 Рейтинг: {card['rating']}\n\n<i>Напиши фамилию ответным сообщением:</i>")
    cur.close(); conn.close()

@dp.message(lambda msg: msg.from_user.id in guessing_game)
async def check_guess(message: types.Message):
    correct = guessing_game.pop(message.from_user.id)
    if message.text.lower() == correct:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + 1000 WHERE user_id = %s", (message.from_user.id,))
        conn.commit(); cur.close(); conn.close()
        await message.answer("✅ Верно! +1000 ⭐")
    else:
        await message.answer(f"❌ Неверно! Это был {correct.capitalize()}")

# --- МАГАЗИН ---
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎫 Стандарт (2.5k)", callback_data="buy_2500")
    kb.button(text="🔥 Премиум (7.5k)", callback_data="buy_7500")
    kb.button(text="💎 Ультимейт (15k)", callback_data="buy_15000")
    await message.answer("🛒 <b>Магазин FTCL:</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(call: types.CallbackQuery):
    price = int(call.data.split("_")[1])
    uid = call.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < price: return await call.answer("❌ Мало ⭐", show_alert=True)
    
    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (price, uid))
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()
    await call.message.answer_photo(card['photo_id'], caption=f"🎁 Куплен пак!\nВыпал: {card['name']}")
    await send_admin_log(f"🛒 {call.from_user.username} купил пак за {price}")

# --- ПРОФИЛЬ И ТОП ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    kb = InlineKeyboardBuilder().button(text="💼 Коллекция", callback_data="my_coll")
    await message.answer(f"👤 <b>Профиль</b>\n💰 Баланс: {u['balance']} ⭐\n🗂 Карт: {cnt}", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.message(F.text == "ТОП-10 📊")
async def top(m: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    res = cur.fetchall()
    txt = "🏆 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]} ⭐" for i, r in enumerate(res)])
    await m.answer(txt); cur.close(); conn.close()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
