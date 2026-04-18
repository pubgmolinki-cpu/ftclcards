import asyncio, psycopg2, os, random, time, logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from psycopg2.extras import DictCursor

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

user_bets = {}
waiting_for_bet = {}
user_cooldowns = {} # Формат: {uid: {"pack": timestamp, "guess": timestamp, "pnl": timestamp}}
user_locks = set()

# Настройки редкостей (для БД на английском)
RARITY_MAP = {
    "legend": {"name": "Легенда", "reward": 10000},
    "ivents": {"name": "Ивентовая", "reward": 5000},
    "brilliant": {"name": "Бриллиантовая", "reward": 2500},
    "gold": {"name": "Золотая", "reward": 1250},
    "bronze": {"name": "Бронзовая", "reward": 500}
}

def get_rarity_key(rating):
    r = int(rating)
    if r >= 99: return "legend"
    if r >= 95: return "ivents"
    if r >= 90: return "brilliant"
    if r >= 75: return "gold"
    return "bronze"

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def check_vip(uid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (uid,))
    res = cur.fetchone()
    cur.close(); conn.close()
    if res and res[0] and res[0] > datetime.now():
        return True
    return False

# --- АДМИНКА ---
@dp.message(Command("add_player"), F.from_user.id == ADMIN_ID)
async def add_player(message: types.Message, command: CommandObject):
    if not message.photo or not command.args:
        return await message.answer("Формат: фото + <code>/add_player Имя | Рейтинг | Клуб | Позиция</code>")
    try:
        args = [a.strip() for a in command.args.split("|")]
        name, rating, club, pos = args
        rarity_key = get_rarity_key(rating)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, club, photo_id, position, rarity) VALUES (%s, %s, %s, %s, %s, %s)",
                    (name, int(rating), club, message.photo[-1].file_id, pos, rarity_key))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Добавлен: {name} ({RARITY_MAP[rarity_key]['name']})")
    except: await message.answer("Ошибка в аргументах!")

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, message.from_user.username))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОЛУЧЕНИЕ КАРТЫ (КД 4ч / VIP 2ч) ---
@dp.message(F.text.lower() == "фтклкарта")
@dp.message(F.text == "Получить Карту 🏆")
async def get_card_free(message: types.Message):
    uid = message.from_user.id
    if uid in user_locks: return
    
    is_vip = await check_vip(uid)
    cd_seconds = 7200 if is_vip else 14400 
    
    now = time.time()
    last_pack = user_cooldowns.get(uid, {}).get("pack", 0)
    if now - last_pack < cd_seconds:
        rem = int(cd_seconds - (now - last_pack))
        return await message.answer(f"⌛ <b>Жди {rem//3600}ч. {(rem%3600)//60}м.</b>")

    user_locks.add(uid)
    try:
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
        card = cur.fetchone()
        
        st = await message.answer("Открываем бесплатный пак... 💼")
        await asyncio.sleep(1); await st.edit_text(f"Позиция: <b>{card['position']}</b>")
        await asyncio.sleep(1); await st.edit_text(f"Рейтинг: <b>{card['rating']}</b>")
        await asyncio.sleep(1); await st.delete()

        reward = RARITY_MAP.get(card['rarity'], RARITY_MAP["bronze"])["reward"]
        
        if uid not in user_cooldowns: user_cooldowns[uid] = {}
        user_cooldowns[uid]["pack"] = time.time()
        
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, uid))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
        conn.commit(); cur.close(); conn.close()

        caption = f"🎉 <b>ВАМ ВЫПАЛА КАРТА!</b>\n\n👤 <b>{card['name'].upper()}</b>\n🧾 Позиция: {card['position']}\n📊 Рейтинг: {card['rating']}\n💰 <b>+{reward} ⭐</b>"
        await message.answer_photo(card['photo_id'], caption=caption)
    finally: user_locks.remove(uid)

# --- МИНИ-ИГРЫ (Угадай игрока: КД 5ч, макс 30к) ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (КД 1ч)", callback_data="game_pnl")
    kb.button(text="🧩 Угадай игрока (КД 5ч)", callback_data="game_guess")
    await message.answer("🎮 <b>Выберите игру:</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("game_"))
async def start_game(call: types.CallbackQuery):
    uid = call.from_user.id
    g_type = call.data.split("_")[1]
    # КД для Угадайки 5 часов (18000 сек)
    cd = 18000 if g_type == "guess" else 3600
    
    if time.time() - user_cooldowns.get(uid, {}).get(g_type, 0) < cd:
        rem = int(cd - (time.time() - user_cooldowns.get(uid, {}).get(g_type, 0)))
        return await call.answer(f"⏳ КД! Осталось {rem//3600}ч. {(rem%3600)//60}м.", show_alert=True)
    
    waiting_for_bet[uid] = g_type
    await call.message.edit_text(f"💰 <b>Введите ставку (Макс: 30,000 ⭐):</b>")

@dp.message(lambda msg: msg.from_user.id in waiting_for_bet)
async def process_bet(message: types.Message):
    uid = message.from_user.id
    g_type = waiting_for_bet.pop(uid)
    if not message.text.isdigit(): return
    bet = min(int(message.text), 30000) # Ограничение ставки

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < bet: return await message.answer("❌ Недостаточно ⭐!")

    user_bets[uid] = {"bet": bet, "game": g_type}
    if g_type == "guess":
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 4")
        cards = cur.fetchall(); correct = cards[0]; random.shuffle(cards)
        kb = InlineKeyboardBuilder()
        for c in cards: kb.button(text=c['name'], callback_data=f"ans_{'y' if c['id']==correct['id'] else 'n'}")
        await message.answer(f"🧩 <b>Угадай игрока!</b>\n🛡 Клуб: {correct['club']}\n📊 Рейтинг: {correct['rating']}", reply_markup=kb.adjust(2).as_markup())
    else:
        kb = InlineKeyboardBuilder().button(text="Лево", callback_data="k_l").button(text="Центр", callback_data="k_c").button(text="Право", callback_data="k_r")
        await message.answer("🥅 Куда бьем?", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith(("ans_", "k_")))
async def game_result(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid not in user_bets: return
    data = user_bets.pop(uid)
    win = (call.data.split("_")[1] == 'y') if "ans_" in call.data else random.choice([True, False])
    
    if uid not in user_cooldowns: user_cooldowns[uid] = {}
    user_cooldowns[uid][data['game']] = time.time()

    conn = get_db_connection(); cur = conn.cursor()
    if win:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (data['bet'], uid))
        msg = f"✅ Победа! +{data['bet']*2} ⭐"
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (data['bet'], uid))
        msg = f"❌ Проигрыш! -{data['bet']} ⭐"
    conn.commit(); cur.close(); conn.close()
    await call.message.edit_text(msg)

# --- МАГАЗИН ---
@dp.message(F.text == "Магазин 🛒")
async def shop_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze Pack (1200⭐)", callback_data="buy_bronze")
    kb.button(text="📦 Gold Pack (3500⭐)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant Pack (6700⭐)", callback_data="buy_brilliant")
    kb.button(text="💎 VIP Status (15000⭐)", callback_data="buy_vip")
    await message.answer("🛒 <b>Магазин</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_item(call: types.CallbackQuery):
    uid = call.from_user.id
    item = call.data.split("_")[1]
    prices = {"bronze": 1200, "gold": 3500, "brilliant": 6700, "vip": 15000}
    price = prices[item]

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < price: return await call.answer("❌ Нет звёзд!", show_alert=True)

    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (price, uid))
    if item == "vip":
        until = datetime.now() + timedelta(days=1)
        cur.execute("UPDATE users SET vip_until = %s WHERE user_id = %s", (until, uid))
        await call.message.answer("💎 <b>VIP куплен!</b> КД на карту теперь 2 часа.")
    else:
        cur.execute("SELECT * FROM all_cards WHERE rarity = %s ORDER BY RANDOM() LIMIT 1", (item,))
        card = cur.fetchone()
        if card:
            cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (RARITY_MAP[item]['reward'], uid))
            await call.message.answer_photo(card['photo_id'], caption=f"📦 Из пака выпал: <b>{card['name']}</b>!")
    conn.commit(); cur.close(); conn.close()
    await call.answer()

# --- ПРОФИЛЬ И ТОП ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance, username, vip_until FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (uid,))
    cnt = cur.fetchone()[0]
    is_v = u['vip_until'] and u['vip_until'] > datetime.now()
    txt = f"👤 @{u['username']}\n💰 Баланс: {u['balance']:,} ⭐\n🃟 Карт: {cnt}\n💎 VIP: {'✅' if is_v else '❌'}"
    await message.answer(txt, reply_markup=InlineKeyboardBuilder().button(text="💼 Коллекция", callback_data="vcoll_0").as_markup())
    cur.close(); conn.close()

@dp.message(F.text == "ТОП-10 📊")
async def top_10(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    txt = "🏆 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]:,} ⭐" for i, r in enumerate(cur.fetchall())])
    await message.answer(txt); cur.close(); conn.close()

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
