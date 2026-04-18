import asyncio, psycopg2, os, random, time, logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from psycopg2.extras import DictCursor

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859)) # Твой ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Временные данные
user_cooldowns = {}
active_matches = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def send_admin_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def check_sub(uid):
    channels = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"]
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

# --- СТАРТ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    ref_id = message.text.split()[1] if len(message.text.split()) > 1 else None
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, message.from_user.username))
    conn.commit(); cur.close(); conn.close()

    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОЛУЧЕНИЕ КАРТЫ (ПО ТВОЕМУ ОПИСАНИЮ И СКРИНУ) ---
@dp.message(F.text == "Получить Карту 🏆")
async def get_pack(message: types.Message):
    uid = message.from_user.id
    if not await check_sub(uid): return await message.answer("❌ Подпишись на каналы!")

    now = time.time()
    if uid in user_cooldowns and now - user_cooldowns[uid] < 14400:
        rem = int(14400 - (now - user_cooldowns[uid]))
        return await message.answer(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}м.")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()

    # ПОШАГОВЫЙ ОПЕНИНГ
    st = await message.answer("Открываем пак... 💼")
    await asyncio.sleep(2)
    await st.edit_text(f"Позиция: <b>{card['position']}</b>")
    await asyncio.sleep(2)
    await st.edit_text(f"Позиция: <b>{card['position']}</b>\nКлуб: <b>{card['club']}</b>")
    await asyncio.sleep(2)
    await st.edit_text(f"Позиция: <b>{card['position']}</b>\nКлуб: <b>{card['club']}</b>\nРейтинг: <b>{card['rating']}</b>")
    await asyncio.sleep(1); await st.delete()

    user_cooldowns[uid] = now
    cur.execute("UPDATE users SET balance = balance + 1250 WHERE user_id = %s", (uid,))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()

    # ШАБЛОН СО СКРИНШОТА
    caption = (
        f"<b>ВАМ ВЫПАЛА НОВАЯ КАРТА</b> 🎉\n\n"
        f"👤 <b>{card['name'].upper()}</b>\n"
        f"📊 <b>Рейтинг: {card['rating']}</b>\n"
        f"🛡 <b>Клуб: {card['club']}</b>\n"
        f"💰 <b>+1250 ⭐</b>"
    )
    await message.answer_photo(card['photo_id'], caption=caption)
    await send_admin_log(f"👤 @{message.from_user.username} выбил {card['name']}")

# --- МИНИ-ИГРЫ (3 ИГРЫ + СТАВКИ + КД) ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (Ставки)", callback_data="game_pnl")
    kb.button(text="🧩 Угадай игрока", callback_data="game_guess")
    kb.button(text="⚔️ PvP Матч", callback_data="game_pvp")
    await message.answer("🎮 <b>Выберите игру:</b>", reply_markup=kb.adjust(1).as_markup())

# 1. Пенальти
@dp.callback_query(F.data == "game_pnl")
async def pnl_bet(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for b in [500, 1000, 5000]: kb.button(text=f"{b} ⭐", callback_data=f"pbet_{b}")
    await call.message.edit_text("💰 Выберите ставку:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pbet_"))
async def pnl_start(call: types.CallbackQuery):
    bet = int(call.data.split("_")[1])
    win = random.choice([True, False])
    conn = get_db_connection(); cur = conn.cursor()
    if win:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, call.from_user.id))
        res = f"✅ ГОООЛ! +{bet} ⭐"
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, call.from_user.id))
        res = f"❌ СЕЙВ! -{bet} ⭐"
    conn.commit(); cur.close(); conn.close()
    await call.message.edit_text(res)

# 2. Угадайка (Выбор из 4)
@dp.callback_query(F.data == "game_guess")
async def guess_start(call: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 4")
    cards = cur.fetchall()
    correct = cards[0]
    random.shuffle(cards)
    kb = InlineKeyboardBuilder()
    for c in cards:
        kb.button(text=c['name'], callback_data=f"ans_{'y' if c['id']==correct['id'] else 'n'}_{correct['id']}")
    await call.message.edit_text(f"🧩 Угадай кто это?\n\n🛡 Клуб: {correct['club']}\n📊 Рейтинг: {correct['rating']}", reply_markup=kb.adjust(2).as_markup())

@dp.callback_query(F.data.startswith("ans_"))
async def guess_check(call: types.CallbackQuery):
    res = call.data.split("_")[1]
    if res == 'y': await call.message.edit_text("✅ Верно! +1000 ⭐")
    else: await call.message.edit_text("❌ Неверно!")

# --- ПРОФИЛЬ И КОЛЛЕКЦИЯ ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    kb = InlineKeyboardBuilder().button(text="💼 Моя коллекция", callback_data="view_coll")
    await message.answer(f"👤 <b>Профиль</b>\n💰 Баланс: {u['balance']:,} ⭐", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "view_coll")
async def view_coll(call: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT c.name, c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s LIMIT 15", (call.from_user.id,))
    res = cur.fetchall()
    txt = "💼 <b>Твои карты:</b>\n\n" + "\n".join([f"▪️ {r[0]} ({r[1]})" for r in res]) if res else "Пусто"
    await call.message.answer(txt); await call.answer()

# --- РЕФЕРАЛКА ---
@dp.message(F.text == "Рефералка 👥")
async def ref(message: types.Message):
    me = await bot.get_me()
    await message.answer(f"👥 Ссылка: <code>t.me/{me.username}?start={message.from_user.id}</code>")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
