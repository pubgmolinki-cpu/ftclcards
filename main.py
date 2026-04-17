import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
import pytz 
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))
PORT = int(os.getenv("PORT", 8080))

# Список каналов
CHANNELS = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"]
VIP_PRICE = 15000
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Словари состояний в памяти
cooldowns = {}          
penalty_cooldowns = {}  
guess_cooldowns = {}
pvp_cooldowns = {}      
temp_photo_buffer = {}  
waiting_for_bet = {}    # {user_id: тип_ожидания}
active_matches = {}     # {match_id: данные_матча}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_now_msk():
    return datetime.now(MOSCOW_TZ)

async def check_subscription(user_id):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except: return False
    return True

def get_vip_info(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        now = get_now_msk()
        if res and res['vip_until']:
            vd = res['vip_until']
            if vd.tzinfo is None: vd = MOSCOW_TZ.localize(vd)
            if vd > now: return True, vd
        return False, None
    finally: cur.close(); conn.close()

def get_stars_by_rating(rating):
    if rating >= 99: return 10000 
    if rating >= 95: return 5000  
    rates = {90: 2500, 85: 2000, 80: 1750, 75: 1500, 70: 1250, 60: 1000, 55: 500}
    for r, val in rates.items():
        if rating >= r: return val
    return 250

def get_card(rarity_filter=None):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        if rarity_filter:
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rarity_filter.lower(),))
        else:
            r = random.randint(1, 1000)
            rtype = "bronze"
            if r == 1: rtype = "legend"
            elif 2 <= r <= 6: rtype = "ivents"
            elif 7 <= r <= 56: rtype = "brilliant" 
            elif 57 <= r <= 206: rtype = "gold"   
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rtype,))
        return cur.fetchone()
    finally: cur.close(); conn.close()

async def animate_card_opening(message, card):
    steps = [
        "📦 <b>Открываем пак...</b>", 
        f"\n\n🏃 Позиция: <b>{card['position']}</b> ⚽", 
        f"\n🛡 Клуб: <b>{card['club']}</b>", 
        f"\n⭐ Рейтинг: <b>{card['rating']}</b>"
    ]
    txt = ""
    for s in steps:
        txt += s
        try:
            await message.edit_text(txt)
            await asyncio.sleep(0.8)
        except: pass
    await asyncio.sleep(0.5)
    await message.delete()

# --- ХЕНДЛЕРЫ ОСНОВНЫЕ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    ref_id = command.args
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
        is_new = cur.fetchone() is None
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                     (user_id, message.from_user.username or "Игрок"))
        if is_new and ref_id and ref_id.isdigit() and int(ref_id) != user_id:
            cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(ref_id),))
            try: await bot.send_message(int(ref_id), "🎁 У вас новый реферал! <b>+1500 ⭐</b>")
            except: pass
        conn.commit()
    finally: cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Реферальная Система 👥"); kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 2)
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        kb = InlineKeyboardBuilder()
        for ch in CHANNELS:
            kb.button(text=f"Подписаться на {ch}", url=f"https://t.me/{ch.replace('@','')}")
        return await message.answer("❌ <b>Чтобы играть, подпишись на все каналы:</b>", reply_markup=kb.adjust(1).as_markup())
    
    is_vip, _ = get_vip_info(user_id)
    limit = 7200 if is_vip else 14400 
    now = time.time()
    if user_id in cooldowns and (now - cooldowns[user_id]) < limit:
        rem = int(limit - (now - cooldowns[user_id]))
        return await message.reply(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}мин.")

    card = get_card()
    if not card: return await message.reply("⚠️ База пуста.")

    cooldowns[user_id] = now
    msg = await message.answer("🔄 Подготовка...")
    await animate_card_opening(msg, card)
    
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
        conn.commit()
        await message.reply_photo(card['photo_id'], caption=f"👤 {card['name']}\n📊 Рейтинг: {card['rating']}\n🛡 {card['club']}\n💰 +{reward} ⭐")
    finally: cur.close(); conn.close()

# --- МИНИ-ИГРЫ МЕНЮ ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (x2)", callback_data="game_penalty")
    kb.button(text="🧩 Угадай Игрока (x2)", callback_data="game_guess")
    kb.button(text="⚔️ Матч (PvP)", callback_data="pvp_info")
    kb.adjust(1)
    await message.answer("🎯 <b>Выберите игру:</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "pvp_info")
async def pvp_info(callback: types.CallbackQuery):
    await callback.message.answer("⚔️ <b>Матч (PvP)</b>\n\nЧтобы вызвать игрока, напишите в группе команду: <code>/match [ставка]</code>\nПример: <code>/match 1000</code>\n\nКулдаун: 1 час.")
    await callback.answer()

# --- ОБНОВЛЕННАЯ СИСТЕМА МАТЧ (PvP) ---

@dp.message(Command("match"))
async def pvp_start(message: types.Message, command: CommandObject):
    if message.chat.type == "private":
        return await message.answer("❌ Матчи проводятся только в группах!")
    
    if not command.args or not command.args.isdigit():
        return await message.answer("❌ Формат: <code>/match 1000</code>")
    
    bet = int(command.args)
    if bet < 100: return await message.answer("❌ Минимальная ставка — 100 ⭐")
    
    user_id = message.from_user.id
    if user_id in pvp_cooldowns and time.time() - pvp_cooldowns[user_id] < 3600:
        rem = int(3600 - (time.time() - pvp_cooldowns[user_id]))
        return await message.answer(f"⏳ Вы еще не восстановили силы! Ждите {rem // 60} мин.")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    u = cur.fetchone()
    if not u or u['balance'] < bet:
        return await message.answer("❌ Недостаточно ⭐ на балансе!")
    cur.close(); conn.close()

    match_id = f"m_{message.chat.id}_{message.message_id}"
    active_matches[match_id] = {
        "p1": user_id, "p1_name": message.from_user.full_name,
        "p2": None, "p2_name": None,
        "bet": bet, "p1_ready": False, "p2_ready": False,
        "p1_pts": 0, "p2_pts": 0
    }

    kb = InlineKeyboardBuilder().button(text=f"Принять вызов ({bet} ⭐) ⚽", callback_data=f"pvpjoin_{match_id}")
    await message.answer(f"🏟 <b>МАТЧ ОБЪЯВЛЕН!</b>\n\n👤 От: {message.from_user.mention_html()}\n💰 Ставка: <b>{bet} ⭐</b>\n\nЖдем оппонента...", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pvpjoin_"))
async def pvp_join(callback: types.CallbackQuery):
    match_id = callback.data.split("_", 1)[1]
    match = active_matches.get(match_id)
    user_id = callback.from_user.id

    if not match: return await callback.answer("Матч не найден.")
    if user_id == match['p1']: return await callback.answer("С собой нельзя!", show_alert=True)
    if match['p2']: return await callback.answer("Место занято.")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    u = cur.fetchone()
    if not u or u['balance'] < match['bet']:
        return await callback.answer("Недостаточно ⭐", show_alert=True)
    
    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (match['bet'], match['p1'], user_id))
    
    def get_pwr(uid):
        cur.execute("SELECT c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id=c.id WHERE uc.user_id=%s ORDER BY RANDOM() LIMIT 3", (uid,))
        r = [x[0] for x in cur.fetchall()]
        return sum(r) if r else random.randint(160, 260)

    match['p1_pts'] = get_pwr(match['p1'])
    match['p2_pts'] = get_pwr(user_id)
    match['p2'] = user_id
    match['p2_name'] = callback.from_user.full_name
    conn.commit(); cur.close(); conn.close()

    for pid, pts in [(match['p1'], match['p1_pts']), (match['p2'], match['p2_pts'])]:
        try: await bot.send_message(pid, f"🎫 <b>Ваш состав готов!</b>\n🔥 Сила: <b>{pts} ПТС</b>")
        except: pass

    kb = InlineKeyboardBuilder().button(text="Играть ✅", callback_data=f"pvpgo_{match_id}")
    await callback.message.edit_text(
        f"⚔️ <b>Оппонент найден!</b>\n\n👤 {match['p1_name']} vs {match['p2_name']}\n💰 Банк: <b>{match['bet']*2} ⭐</b>\n\n"
        f"📩 <b>Отправил вам в личные сообщения ваши составы 📑</b>\nНажмите кнопку ниже!", reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("pvpgo_"))
async def pvp_ready(callback: types.CallbackQuery):
    match_id = callback.data.split("_", 1)[1]
    match = active_matches.get(match_id)
    uid = callback.from_user.id

    if not match: return await callback.answer("Ошибка.")
    if uid != match['p1'] and uid != match['p2']: return await callback.answer("Вы не в игре.", show_alert=True)

    if uid == match['p1']: match['p1_ready'] = True
    if uid == match['p2']: match['p2_ready'] = True
    await callback.answer("Готов! ✅")

    if match['p1_ready'] and match['p2_ready']:
        pvp_cooldowns[match['p1']] = pvp_cooldowns[match['p2']] = time.time()
        for stage in ["⚽️ Свисток!", "🏃 Борьба в центре...", "⚡️ Опасный момент!", "⏱ Финальные секунды..."]:
            await callback.message.edit_text(f"🏟 <b>МАТЧ ИДЕТ:</b>\n\n{stage}"); await asyncio.sleep(1.5)

        p1, p2, bank = match['p1_pts'], match['p2_pts'], match['bet']*2
        res = f"🏁 <b>ИТОГ:</b>\n\n📊 {match['p1_name']}: {p1}\n📊 {match['p2_name']}: {p2}\n\n"
        
        conn = get_db_connection(); cur = conn.cursor()
        if p1 > p2:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (bank, match['p1']))
            res += f"🏆 Победил <b>{match['p1_name']}</b>! +{bank} ⭐"
        elif p2 > p1:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (bank, match['p2']))
            res += f"🏆 Победил <b>{match['p2_name']}</b>! +{bank} ⭐"
        else:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s,%s)", (match['bet'], match['p1'], match['p2']))
            res += "🤝 Ничья! Ставки вернулись."
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(res); active_matches.pop(match_id, None)

# --- УГАДАЙ ИГРОКА ---
@dp.callback_query(F.data == "game_guess")
async def guess_init(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in guess_cooldowns and time.time() - guess_cooldowns[uid] < 21600:
        rem = int(21600 - (time.time() - guess_cooldowns[uid]))
        return await callback.answer(f"⏳ КД! Жди {rem//3600}ч.", show_alert=True)
    waiting_for_bet[uid] = "guess"
    await callback.message.edit_text("💰 Введите ставку (1,000 - 100,000 ⭐):")

async def run_guess_game(message: types.Message, bet: int):
    uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
        if cur.fetchone()['balance'] < bet: return await message.answer("❌ Недостаточно ⭐")
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
        target = cur.fetchone()
        cur.execute("SELECT name FROM all_cards WHERE name != %s ORDER BY RANDOM() LIMIT 3", (target['name'],))
        names = [target['name']] + [r['name'] for r in cur.fetchall()]
        random.shuffle(names)
        kb = InlineKeyboardBuilder()
        for n in names: kb.button(text=n, callback_data=f"gs_{'w' if n == target['name'] else 'l'}_{bet}")
        guess_cooldowns[uid] = time.time(); conn.commit()
        await message.answer(f"🧩 <b>Угадай, кто это?</b>\n\n🛡 Клуб: {target['club']}\n📊 Рейтинг: {target['rating']}\n🏃 Поз: {target['position']}", reply_markup=kb.adjust(2).as_markup())
    finally: cur.close(); conn.close()

@dp.callback_query(F.data.startswith("gs_"))
async def guess_check(callback: types.CallbackQuery):
    _, res, bet = callback.data.split("_"); bet = int(bet)
    if res == 'w':
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet*2, callback.from_user.id))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"✅ Правильно! Вы выиграли {bet*2} ⭐")
    else:
        await callback.message.edit_text(f"❌ Неверно! Ставка {bet} ⭐ потеряна.")

# --- ПЕНАЛЬТИ ---
@dp.callback_query(F.data == "game_penalty")
async def penalty_init(callback: types.CallbackQuery):
    waiting_for_bet[callback.from_user.id] = "penalty"
    await callback.message.edit_text("💰 Введите ставку на пенальти:")

async def run_penalty(message: types.Message, bet: int):
    kb = InlineKeyboardBuilder()
    for s in ["Лево ⬅️", "Центр ⬆️", "Право ➡️"]: kb.button(text=s, callback_data=f"pnl_{bet}")
    await message.answer(f"🥅 Ставка {bet} ⭐. Куда бьем?", reply_markup=kb.adjust(3).as_markup())

@dp.callback_query(F.data.startswith("pnl_"))
async def penalty_finish(callback: types.CallbackQuery):
    bet = int(callback.data.split("_")[1])
    if random.choice([True, False]):
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, callback.from_user.id))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"⚽️ ГОЛ! +{bet} ⭐")
    else:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, callback.from_user.id))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"🧤 Вратарь отбил! -{bet} ⭐")

# --- ОБЩИЙ ОБРАБОТЧИК СТАВОК ---
@dp.message(lambda m: m.from_user.id in waiting_for_bet)
async def handle_bets(message: types.Message):
    state = waiting_for_bet.pop(message.from_user.id)
    if not message.text.isdigit(): return
    val = int(message.text)
    if state == "guess": await run_guess_game(message, val)
    elif state == "penalty": await run_penalty(message, val)

# --- ПРОФИЛЬ И СИСТЕМА ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    kb = InlineKeyboardBuilder().button(text="Коллекция 💼", callback_data="my_collection")
    await message.reply(f"👤 <b>@{message.from_user.username}</b>\n💰 Баланс: <b>{u['balance'] if u else 0}</b> ⭐\n🗂 Карт: <b>{cnt}</b>", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data == "my_collection")
async def show_collection(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT c.name, c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id=c.id WHERE uc.user_id=%s ORDER BY c.rating DESC LIMIT 30", (callback.from_user.id,))
    cards = cur.fetchall()
    if not cards: return await callback.answer("Пусто!")
    txt = "💼 <b>Топ-30 карт:</b>\n\n" + "\n".join([f"• {c[0]} ({c[1]})" for c in cards])
    await callback.message.answer(txt); await callback.answer(); cur.close(); conn.close()

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall(); cur.close(); conn.close()
    await message.answer("📊 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} - {r[1]}⭐" for i, r in enumerate(top)]))

@dp.message(F.text == "Магазин 🛒")
async def shop_menu(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="📦 Gold (5.7к)", callback_data="buy_gold").button(text="📦 Brilliant (7к)", callback_data="buy_brilliant")
    await message.answer("🛒 Магазин паков:", reply_markup=kb.adjust(1).as_markup())

@dp.message(F.text == "Реферальная Система 👥")
async def ref_link(message: types.Message):
    bot_info = await bot.get_me()
    await message.answer(f"👥 Ссылка: <code>https://t.me/{bot_info.username}?start={message.from_user.id}</code>\n+1500 ⭐ за друга!")

# --- АДМИНКА ---
@dp.message(F.photo & (F.from_user.id == ADMIN_ID))
async def handle_photo(message: types.Message):
    temp_photo_buffer[ADMIN_ID] = message.photo[-1].file_id
    await message.reply("📸 Фото ОК. Жду: `/add_player Имя, Рейтинг, Поз, Клуб`")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(ADMIN_ID)
    if not p_id: return await message.reply("❌ Сначала фото!")
    try:
        a = message.text.replace("/add_player ", "").split(",")
        name, rat, pos, club = a[0].strip(), int(a[1].strip()), a[2].strip(), a[3].strip()
        rt = "legend" if rat >= 99 else "ivents" if rat >= 95 else "brilliant" if rat >= 90 else "gold" if rat >= 75 else "bronze"
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                     (name, rat, pos, rt.capitalize(), rt, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Добавлен {name}!"); del temp_photo_buffer[ADMIN_ID]
    except: await message.answer("❌ Ошибка формата!")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
