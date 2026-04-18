import asyncio, psycopg2, os, random, time, logging
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
user_locks = set()  # Блокировка от спама

# Награды за редкость
RARITY_REWARDS = {
    "bronze": 500,
    "gold": 1250,
    "brilliant": 2500,
    "ivents": 5000,
    "legend": 10000
}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def send_admin_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

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
        await send_admin_log(f"👥 Реферал! @{message.from_user.username} приглашен юзером {ref_id}")
    
    conn.commit(); cur.close(); conn.close()

    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОЛУЧЕНИЕ КАРТЫ (С ЗАЩИТОЙ ОТ СПАМА) ---
@dp.message(F.text.lower() == "фтклкарта")
@dp.message(F.text == "Получить Карту 🏆")
async def get_card(message: types.Message):
    uid = message.from_user.id
    
    # 1. Защита от спама (Lock)
    if uid in user_locks:
        return # Просто игнорируем нажатие, если процесс уже идет

    # 2. Проверка подписки
    not_sub = await get_not_subscribed_channels(uid)
    if not_sub:
        kb = InlineKeyboardBuilder()
        for i, (name, url) in enumerate(not_sub, 1): kb.button(text=f"Канал {i} 📢", url=url)
        kb.button(text="Я подписался ✅", callback_data="check_subs")
        return await message.answer("❌ <b>Подпишись на каналы!</b>", reply_markup=kb.adjust(1).as_markup())

    # 3. Проверка КД
    now = time.time()
    last_pack = user_cooldowns.get(uid, {}).get("pack", 0)
    if now - last_pack < 14400:
        rem = int(14400 - (now - last_pack))
        return await message.answer(f"⌛ <b>Жди {rem//3600}ч. {(rem%3600)//60}м.</b>")

    # Ставим блокировку
    user_locks.add(uid)

    try:
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
        card = cur.fetchone()
        
        if not card:
            user_locks.remove(uid)
            return await message.answer("Ошибка: Карты не найдены.")

        # Анимация
        st = await message.answer("Открываем пак... 💼")
        await asyncio.sleep(1); await st.edit_text(f"Позиция: <b>{card['position']}</b>")
        await asyncio.sleep(1); await st.edit_text(f"Рейтинг: <b>{card['rating']}</b>")
        await asyncio.sleep(1); await st.edit_text(f"Клуб: <b>{card['club']}</b>")
        await asyncio.sleep(1); await st.delete()

        reward = RARITY_REWARDS.get(card['rarity'], 500)

        # Обновляем КД и БД
        if uid not in user_cooldowns: user_cooldowns[uid] = {}
        user_cooldowns[uid]["pack"] = time.time()
        
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, uid))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
        conn.commit(); cur.close(); conn.close()

        caption = (
            f"🎉 <b>ВАМ ВЫПАЛА НОВАЯ КАРТА!</b> 🎉\n\n"
            f"👤 <b>{card['name'].upper()}</b>\n"
            f"🧾Позиция: <b>{card['position']}</b>\n"
            f"📊 Рейтинг: <b>{card['rating']}</b>\n"
            f"🛡 Клуб: <b>{card['club']}</b>\n"
            f"💰 <b>+{reward} ⭐</b>"
        )
        await message.answer_photo(card['photo_id'], caption=caption)
        
    finally:
        # Снимаем блокировку в любом случае (даже если была ошибка)
        if uid in user_locks:
            user_locks.remove(uid)

# --- ПРОФИЛЬ ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance, username FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (uid,))
    card_count = cur.fetchone()[0]
    
    txt = (
        f"👤 <b>Профиль игрока</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"📎 Юзер: @{u['username']}\n"
        f"💰 Баланс: {u['balance']:,} ⭐\n"
        f"🃟 Карт в коллекции: <b>{card_count}</b>"
    )
    kb = InlineKeyboardBuilder().button(text="💼 Моя коллекция", callback_data="vcoll_0")
    await message.answer(txt, reply_markup=kb.as_markup())
    cur.close(); conn.close()

# --- КОЛЛЕКЦИЯ С ПАГИНАЦИЕЙ ---
@dp.callback_query(F.data.startswith("vcoll_"))
async def view_collection(call: types.CallbackQuery):
    page = int(call.data.split("_")[1])
    offset = page * 15
    uid = call.from_user.id
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT c.name, c.rating FROM user_cards uc 
        JOIN all_cards c ON uc.card_id = c.id 
        WHERE uc.user_id = %s 
        ORDER BY c.rating DESC 
        LIMIT 15 OFFSET %s
    """, (uid, offset))
    res = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (uid,))
    total_cards = cur.fetchone()[0]
    
    if not res and page == 0:
        return await call.answer("Коллекция пуста!", show_alert=True)
    
    txt = f"💼 <b>Твоя коллекция (Стр. {page + 1}):</b>\n\n"
    for r in res: txt += f"▪️ {r[0]} — <b>{r[1]}</b>\n"
    
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️ Назад", callback_data=f"vcoll_{page - 1}")
    if total_cards > offset + 15:
        kb.button(text="Вперед ➡️", callback_data=f"vcoll_{page + 1}")
    
    await call.message.edit_text(txt, reply_markup=kb.adjust(2).as_markup())
    cur.close(); conn.close()

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (КД 1ч)", callback_data="game_pnl")
    kb.button(text="🧩 Угадай игрока (КД 2ч)", callback_data="game_guess")
    await message.answer("🎮 <b>Выберите игру:</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("game_"))
async def start_game(call: types.CallbackQuery):
    uid = call.from_user.id
    g_type = call.data.split("_")[1]
    cd = 3600 if g_type == "pnl" else 7200
    if time.time() - user_cooldowns.get(uid, {}).get(g_type, 0) < cd:
        return await call.answer("⏳ КД еще не прошло!", show_alert=True)
    waiting_for_bet[uid] = g_type
    await call.message.edit_text("💰 <b>Введите сумму вашей ставки:</b>")

@dp.message(lambda msg: msg.from_user.id in waiting_for_bet)
async def process_bet(message: types.Message):
    uid = message.from_user.id
    g_type = waiting_for_bet.pop(uid)
    if not message.text.isdigit(): return
    bet = int(message.text)
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < bet: 
        cur.close(); conn.close()
        return await message.answer("❌ Недостаточно ⭐!")

    user_bets[uid] = {"bet": bet, "game": g_type}
    if g_type == "pnl":
        kb = InlineKeyboardBuilder().button(text="Лево ⬅️", callback_data="k_l").button(text="Центр ⬆️", callback_data="k_c").button(text="Право ➡️", callback_data="k_r")
        await message.answer(f"⚽ Ставка {bet} принята! Бей:", reply_markup=kb.as_markup())
    elif g_type == "guess":
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 4")
        cards = cur.fetchall(); correct = cards[0]; random.shuffle(cards)
        kb = InlineKeyboardBuilder()
        for c in cards: kb.button(text=c['name'], callback_data=f"ans_{'y' if c['id']==correct['id'] else 'n'}")
        await message.answer(f"🧩 Угадай игрока ({bet} ⭐)\n🛡 Клуб: {correct['club']}\n📊 Рейтинг: {correct['rating']}", reply_markup=kb.adjust(2).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("k_"))
@dp.callback_query(F.data.startswith("ans_"))
async def res_game(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid not in user_bets: return
    bet = user_bets.pop(uid)['bet']
    win = random.choice([True, False]) if "k_" in call.data else (call.data.split("_")[1] == 'y')
    
    conn = get_db_connection(); cur = conn.cursor()
    if win:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, uid))
        msg = f"✅ Победа! +{bet*2} ⭐"
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
        msg = f"❌ Проигрыш! -{bet} ⭐"
    conn.commit(); cur.close(); conn.close()
    await call.message.edit_text(msg)

# --- ТОП-10 ---
@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    txt = "🏆 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]:,} ⭐" for i, r in enumerate(cur.fetchall())])
    await message.answer(txt); cur.close(); conn.close()

# --- РЕФЕРАЛКА ---
@dp.message(F.text == "Рефералка 👥")
async def reflink(message: types.Message):
    me = await bot.get_me()
    await message.answer(f"👥 <b>Рефералка</b>\nЗа друга: 5,000 ⭐\n Ссылка:\n<code>t.me/{me.username}?start={message.from_user.id}</code>")

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
