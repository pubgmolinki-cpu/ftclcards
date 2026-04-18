import asyncio, psycopg2, os, random, time, logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from psycopg2.extras import DictCursor

# --- НАСТРОЙКИ (Заполни своими данными) ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Кэш в памяти
user_bets = {}
waiting_for_bet = {}
user_cooldowns = {}
user_locks = set()

# Настройки редкостей (названия в БД на английском)
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
    if res and res[0] and res[0] > datetime.now(): return True
    return False

async def get_not_subscribed_channels(uid):
    not_subscribed = []
    channels = {
        "@ftclcardschannel": "https://t.me/ftclcardschannel", 
        "@waxteamiftl": "https://t.me/waxteamiftl", 
        "@ftcloff": "https://t.me/ftcloff"
    }
    for ch_name, ch_url in channels.items():
        try:
            m = await bot.get_chat_member(ch_name, uid)
            if m.status not in ["member", "administrator", "creator"]: 
                not_subscribed.append((ch_name, ch_url))
        except: 
            not_subscribed.append((ch_name, ch_url))
    return not_subscribed

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
        await message.answer(f"✅ Карта <b>{name}</b> ({rating}) добавлена!\nРедкость: {RARITY_MAP[rarity_key]['name']}")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")

# --- СТАРТ И РЕФЕРАЛКА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    args = message.text.split()
    ref_id = args[1] if len(args) > 1 and args[1].isdigit() else None
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (uid,))
    is_new = cur.fetchone() is None
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, message.from_user.username))
    if is_new and ref_id and int(ref_id) != uid:
        cur.execute("UPDATE users SET balance = balance + 5000 WHERE user_id = %s", (int(ref_id),))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОЛУЧЕНИЕ КАРТЫ (С ШАНСАМИ) ---
@dp.message(F.text == "Получить Карту 🏆")
async def get_card_free(message: types.Message):
    uid = message.from_user.id
    if uid in user_locks: return
    
    not_sub = await get_not_subscribed_channels(uid)
    if not_sub:
        kb = InlineKeyboardBuilder()
        for i, (n, u) in enumerate(not_sub, 1): kb.button(text=f"Канал {i} 📢", url=u)
        kb.button(text="Я подписался ✅", callback_data="check_subs")
        return await message.answer("❌ <b>Подпишись на каналы для получения карты!</b>", reply_markup=kb.adjust(1).as_markup())

    is_v = await check_vip(uid)
    cd = 7200 if is_v else 14400 # 2 часа VIP / 4 часа Обычный
    if time.time() - user_cooldowns.get(uid, {}).get("pack", 0) < cd:
        rem = int(cd - (time.time() - user_cooldowns.get(uid, {}).get("pack", 0)))
        return await message.answer(f"⌛ <b>Жди {rem//3600}ч. {(rem%3600)//60}м.</b>")

    user_locks.add(uid)
    try:
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
        
        # Настройка шансов
        rarities = ["bronze", "gold", "brilliant", "ivents", "legend"]
        weights = [70, 20, 5, 3, 2] # Проценты
        selected = random.choices(rarities, weights=weights, k=1)[0]
        
        ranges = {
            "bronze": "BETWEEN 50 AND 70", "gold": "BETWEEN 75 AND 85", 
            "brilliant": "= 90", "ivents": "BETWEEN 95 AND 98", "legend": ">= 99"
        }
        
        cur.execute(f"SELECT * FROM all_cards WHERE rating {ranges[selected]} ORDER BY RANDOM() LIMIT 1")
        card = cur.fetchone()
        if not card: # Страховка, если категория пуста
            cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
            card = cur.fetchone()

        if not card: return await message.answer("В базе пусто.")

        st = await message.answer("Открываем пак... 💼"); await asyncio.sleep(2); await st.delete()
        
        reward = RARITY_MAP.get(card['rarity'], {"reward": 500})["reward"]
        if uid not in user_cooldowns: user_cooldowns[uid] = {}
        user_cooldowns[uid]["pack"] = time.time()
        
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, uid))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
        conn.commit(); cur.close(); conn.close()
        
        await message.answer_photo(card['photo_id'], caption=f"👤 <b>{card['name']}</b>\n📊 Рейтинг: {card['rating']}\n💰 Награда: +{reward} ⭐")
    finally: user_locks.remove(uid)

# --- МАГАЗИН ---
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze (1200⭐)", callback_data="buy_bronze")
    kb.button(text="📦 Gold (3500⭐)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant (6700⭐)", callback_data="buy_brilliant")
    kb.button(text="💎 VIP 30d (15000⭐)", callback_data="buy_vip")
    await message.answer("🛒 <b>Магазин FTCL</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: types.CallbackQuery):
    uid = call.from_user.id
    item = call.data.split("_")[1]
    prices = {"bronze": 1200, "gold": 3500, "brilliant": 6700, "vip": 15000}
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    if u['balance'] < prices[item]: return await call.answer("❌ Недостаточно ⭐!", show_alert=True)
    
    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (prices[item], uid))
    if item == "vip":
        until = datetime.now() + timedelta(days=30)
        cur.execute("UPDATE users SET vip_until = %s WHERE user_id = %s", (until, uid))
        await call.message.answer("💎 VIP активирован на 30 дней!")
    else:
        q = {"bronze": "BETWEEN 50 AND 70", "gold": "BETWEEN 75 AND 85", "brilliant": "= 90"}[item]
        cur.execute(f"SELECT * FROM all_cards WHERE rating {q} ORDER BY RANDOM() LIMIT 1")
        card = cur.fetchone()
        if card:
            cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
            rew = RARITY_MAP.get(card['rarity'], {"reward": 500})["reward"]
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (rew, uid))
            await call.message.answer_photo(card['photo_id'], caption=f"📦 Выпал: {card['name']}!")
    conn.commit(); cur.close(); conn.close(); await call.answer()

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="🧩 Угадай игрока (КД 5ч)", callback_data="game_guess").as_markup()
    await message.answer("🎮 Выбери игру:", reply_markup=kb)

@dp.callback_query(F.data == "game_guess")
async def start_guess(call: types.CallbackQuery):
    uid = call.from_user.id
    if time.time() - user_cooldowns.get(uid, {}).get("guess", 0) < 18000: # 5 часов
        rem = int(18000 - (time.time() - user_cooldowns.get(uid, {}).get("guess", 0)))
        return await call.answer(f"⏳ КД! Жди {rem//3600}ч.", show_alert=True)
    waiting_for_bet[uid] = "guess"; await call.message.edit_text("💰 Введи ставку (макс 30000):")

@dp.message(lambda msg: msg.from_user.id in waiting_for_bet)
async def bet_handler(message: types.Message):
    uid = message.from_user.id
    if not message.text.isdigit(): return
    bet = int(message.text)
    if bet > 30000: return await message.answer("❌ Ошибка: Максимальная ставка 30,000 ⭐!")
    waiting_for_bet.pop(uid)
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < bet: return await message.answer("❌ Недостаточно ⭐!")
    
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 4")
    cards = cur.fetchall(); correct = cards[0]; random.shuffle(cards)
    user_bets[uid] = {"bet": bet, "corr": correct['id'], "game": "guess"}
    kb = InlineKeyboardBuilder()
    for c in cards: kb.button(text=c['name'], callback_data=f"ans_{c['id']}")
    await message.answer(f"🧩 <b>Угадай игрока!</b>\n🛡 Клуб: {correct['club']}\n📊 Рейтинг: {correct['rating']}", reply_markup=kb.adjust(2).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("ans_"))
async def ans_handler(call: types.CallbackQuery):
    uid = call.from_user.id; ans_id = int(call.data.split("_")[1])
    if uid not in user_bets: return
    data = user_bets.pop(uid); win = (ans_id == data['corr'])
    
    if uid not in user_cooldowns: user_cooldowns[uid] = {}
    user_cooldowns[uid]["guess"] = time.time()
    
    conn = get_db_connection(); cur = conn.cursor()
    change = data['bet'] if win else -data['bet']
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (change, uid))
    conn.commit(); cur.close(); conn.close()
    await call.message.edit_text(f"{'✅ Победа! +' if win else '❌ Проигрыш! -'}{data['bet']} ⭐")

# --- КОЛЛЕКЦИЯ, ПРОФИЛЬ, ТОП ---
@dp.callback_query(F.data.startswith("vcoll_"))
async def collection(call: types.CallbackQuery):
    page = int(call.data.split("_")[1]); uid = call.from_user.id
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT c.name, c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s ORDER BY c.rating DESC LIMIT 15 OFFSET %s", (uid, page*15))
    res = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (uid,))
    total = cur.fetchone()[0]
    txt = f"💼 <b>Твоя коллекция (Стр. {page+1}):</b>\n\n" + "\n".join([f"▪️ {r[0]} — <b>{r[1]}</b>" for r in res])
    kb = InlineKeyboardBuilder()
    if page > 0: kb.button(text="⬅️ Назад", callback_data=f"vcoll_{page-1}")
    if total > (page+1)*15: kb.button(text="Вперед ➡️", callback_data=f"vcoll_{page+1}")
    await call.message.edit_text(txt, reply_markup=kb.adjust(2).as_markup()); cur.close(); conn.close()

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance, username, vip_until FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    is_v = u['vip_until'] and u['vip_until'] > datetime.now()
    await message.answer(f"👤 <b>Профиль @{u['username']}</b>\n💰 Баланс: {u['balance']:,} ⭐\n💎 VIP: {'✅' if is_v else '❌'}", 
                         reply_markup=InlineKeyboardBuilder().button(text="💼 Коллекция", callback_data="vcoll_0").as_markup())
    cur.close(); conn.close()

@dp.message(F.text == "Рефералка 👥")
async def ref(message: types.Message):
    me = await bot.get_me()
    await message.answer(f"👥 <b>Рефералка</b>\n\n5000 ⭐ за друга!\nСсылка:\n<code>t.me/{me.username}?start={message.from_user.id}</code>")

@dp.message(F.text == "ТОП-10 📊")
async def top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    txt = "🏆 <b>ТОП-10 Игроков:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]:,} ⭐" for i, r in enumerate(cur.fetchall())])
    await message.answer(txt); cur.close(); conn.close()

@dp.callback_query(F.data == "check_subs")
async def check_s(call: types.CallbackQuery):
    if not await get_not_subscribed_channels(call.from_user.id): 
        await call.message.delete(); await call.message.answer("✅ Подписка подтверждена! Жми 'Получить Карту'")
    else: 
        await call.answer("❌ Вы не подписаны на все каналы!", show_alert=True)

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
