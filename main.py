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
user_cooldowns = {}
user_locks = set()

RARITY_MAP = {
    "legend": {"name": "Легенда", "reward": 10000},
    "ivents": {"name": "Ивентовая", "reward": 5000},
    "brilliant": {"name": "Бриллиантовая", "reward": 2500},
    "gold": {"name": "Золотая", "reward": 1250},
    "bronze": {"name": "Бронзовая", "reward": 500}
}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def check_vip(uid):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (uid,))
    res = cur.fetchone()
    cur.close(); conn.close()
    if res and res[0] and res[0] > datetime.now(): return True
    return False

# ПРОВЕРКА ПОДПИСКИ
async def get_not_subscribed_channels(uid):
    not_subscribed = []
    channels_info = {
        "@ftclcardschannel": "https://t.me/ftclcardschannel", 
        "@waxteamiftl": "https://t.me/waxteamiftl", 
        "@ftcloff": "https://t.me/ftcloff"
    }
    for ch_name, ch_url in channels_info.items():
        try:
            m = await bot.get_chat_member(ch_name, uid)
            if m.status not in ["member", "administrator", "creator"]:
                not_subscribed.append((ch_name, ch_url))
        except:
            not_subscribed.append((ch_name, ch_url))
    return not_subscribed

# --- ГЛАВНОЕ МЕНЮ ---
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

# --- ПОЛУЧЕНИЕ КАРТЫ (С ПРОВЕРКОЙ ПОДПИСКИ) ---
@dp.message(F.text == "Получить Карту 🏆")
async def get_card_free(message: types.Message):
    uid = message.from_user.id
    if uid in user_locks: return
    
    # ПРОВЕРКА ПОДПИСКИ ПЕРЕД ВЫДАЧЕЙ
    not_sub = await get_not_subscribed_channels(uid)
    if not_sub:
        kb = InlineKeyboardBuilder()
        for i, (name, url) in enumerate(not_sub, 1):
            kb.button(text=f"Канал {i} 📢", url=url)
        kb.button(text="Я подписался ✅", callback_data="check_subs")
        return await message.answer("❌ <b>Для получения бесплатной карты нужно подписаться на наши каналы!</b>", 
                                   reply_markup=kb.adjust(1).as_markup())

    is_vip = await check_vip(uid)
    cd = 7200 if is_vip else 14400 
    now = time.time()
    if now - user_cooldowns.get(uid, {}).get("pack", 0) < cd:
        rem = int(cd - (now - user_cooldowns.get(uid, {}).get("pack", 0)))
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

        reward = RARITY_MAP.get(card['rarity'], {"reward": 500})["reward"]
        if uid not in user_cooldowns: user_cooldowns[uid] = {}
        user_cooldowns[uid]["pack"] = time.time()
        
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, uid))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
        conn.commit(); cur.close(); conn.close()

        caption = f"🎉 <b>ВАМ ВЫПАЛА КАРТА!</b>\n\n👤 <b>{card['name'].upper()}</b>\n📊 Рейтинг: {card['rating']}\n💰 <b>+{reward} ⭐</b>"
        await message.answer_photo(card['photo_id'], caption=caption)
    finally: user_locks.remove(uid)

# КНОПКА "Я ПОДПИСАЛСЯ"
@dp.callback_query(F.data == "check_subs")
async def check_subs_callback(call: types.CallbackQuery):
    not_sub = await get_not_subscribed_channels(call.from_user.id)
    if not_sub:
        await call.answer("❌ Вы всё еще не подписаны на все каналы!", show_alert=True)
    else:
        await call.message.delete()
        await call.message.answer("✅ Подписка подтверждена! Теперь нажми «Получить Карту 🏆»")

# --- МАГАЗИН (Bronze: 50-70, Gold: 75-85, Brilliant: 90) ---
@dp.callback_query(F.data.startswith("buy_"))
async def process_purchase(call: types.CallbackQuery):
    uid = call.from_user.id
    item = call.data.split("_")[1]
    prices = {"bronze": 1200, "gold": 3500, "brilliant": 6700, "vip": 15000}
    price = prices[item]

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    user = cur.fetchone()

    if user['balance'] < price:
        return await call.answer("❌ Недостаточно ⭐!", show_alert=True)

    if item == "vip":
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (price, uid))
        until = datetime.now() + timedelta(days=30)
        cur.execute("UPDATE users SET vip_until = %s WHERE user_id = %s", (until, uid))
        conn.commit(); cur.close(); conn.close()
        return await call.message.answer("💎 <b>VIP-статус активирован!</b>")

    query_map = {
        "bronze": "SELECT * FROM all_cards WHERE rating BETWEEN 50 AND 70 ORDER BY RANDOM() LIMIT 1",
        "gold": "SELECT * FROM all_cards WHERE rating BETWEEN 75 AND 85 ORDER BY RANDOM() LIMIT 1",
        "brilliant": "SELECT * FROM all_cards WHERE rating = 90 ORDER BY RANDOM() LIMIT 1"
    }

    cur.execute(query_map[item])
    card = cur.fetchone()
    if not card:
        cur.close(); conn.close()
        return await call.answer("❌ Карт этого типа нет в базе!", show_alert=True)

    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (price, uid))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    reward = RARITY_MAP.get(card['rarity'], {"reward": 500})["reward"]
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, uid))
    conn.commit(); cur.close(); conn.close()

    await call.message.answer_photo(card['photo_id'], caption=f"📦 Из пака выпал: <b>{card['name']}</b> ({card['rating']})!")
    await call.answer()

# --- ИГРЫ (Угадай игрока: КД 5ч, макс 30к) ---
@dp.message(lambda msg: msg.from_user.id in waiting_for_bet)
async def process_bet(message: types.Message):
    uid = message.from_user.id
    g_type = waiting_for_bet[uid]
    if not message.text.isdigit(): return
    bet = int(message.text)
    
    if bet > 30000:
        return await message.answer("❌ <b>Ошибка:</b> Максимальная ставка — 30,000 ⭐!")
    
    waiting_for_bet.pop(uid)
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < bet: 
        cur.close(); conn.close()
        return await message.answer("❌ Недостаточно ⭐!")

    user_bets[uid] = {"bet": bet, "game": g_type}
    if g_type == "guess":
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 4")
        cards = cur.fetchall(); correct = cards[0]; random.shuffle(cards)
        kb = InlineKeyboardBuilder()
        for c in cards: kb.button(text=c['name'], callback_data=f"ans_{'y' if c['id']==correct['id'] else 'n'}")
        await message.answer(f"🧩 Угадай игрока!\n🛡 Клуб: {correct['club']}\n📊 Рейтинг: {correct['rating']}", reply_markup=kb.adjust(2).as_markup())
    else:
        kb = InlineKeyboardBuilder().button(text="Лево", callback_data="k_l").button(text="Центр", callback_data="k_c").button(text="Право", callback_data="k_r")
        await message.answer("🥅 Куда бьем?", reply_markup=kb.as_markup())
    cur.close(); conn.close()

# --- ПРОФИЛЬ, ТОП, РЕФЕРАЛКА, МАГАЗИН, КОЛЛЕКЦИЯ ---
# (эти функции остаются такими же, как в предыдущем сообщении)
# ...

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
