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

CHANNELS = ["@ftclcardschannel", "@waxteamiftl"]
VIP_PRICE = 15000
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Словари для хранения состояний в памяти
cooldowns = {}          
penalty_cooldowns = {}  
temp_photo_buffer = {}  
waiting_for_bet = {}    

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
        except: 
            return False
    return True

def get_vip_info(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        now = get_now_msk()
        if res and res['vip_until']:
            vd = res['vip_until']
            if vd.tzinfo is None: vd = MOSCOW_TZ.localize(vd)
            if vd > now: return True, vd
        return False, None
    finally: 
        cur.close()
        conn.close()

# --- ЛОГИКА КАРТ ---
def get_stars_by_rating(rating):
    if rating >= 99: return 10000 
    if rating >= 95: return 5000  
    rates = {90: 2500, 85: 2000, 80: 1750, 75: 1500, 70: 1250, 60: 1000, 55: 500}
    for r, val in rates.items():
        if rating >= r: return val
    return 250

def get_card(rarity_filter=None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    try:
        if rarity_filter:
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rarity_filter.lower(),))
        else:
            r = random.randint(1, 1000)
            if r == 1: rtype = "legend"
            elif 2 <= r <= 6: rtype = "ivents"
            elif 7 <= r <= 56: rtype = "brilliant" 
            elif 57 <= r <= 206: rtype = "gold"   
            else: rtype = "bronze" 
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rtype,))
        return cur.fetchone()
    finally: 
        cur.close()
        conn.close()

async def animate_card_opening(message, card):
    base_text = "📦 <b>Открываем пак...</b>"
    try:
        await message.edit_text(base_text)
        await asyncio.sleep(0.7)
        base_text += f"\n\n🏃 Позиция: <b>{card['position']}</b> ⚽"
        await message.edit_text(base_text)
        await asyncio.sleep(0.7)
        base_text += f"\n🛡 Клуб: <b>{card['club']}</b>"
        await message.edit_text(base_text)
        await asyncio.sleep(0.7)
        base_text += f"\n⭐ Рейтинг: <b>{card['rating']}</b>"
        await message.edit_text(base_text)
        await asyncio.sleep(0.8)
        await message.delete()
    except: pass

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    ref_id = command.args
    conn = get_db_connection()
    cur = conn.cursor()
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
    finally: 
        cur.close()
        conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Реферальная Система 👥"); kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 2)
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Получить Карту 🏆")
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    
    # 1. Проверка подписки
    if not await check_subscription(user_id):
        kb = InlineKeyboardBuilder()
        for ch in CHANNELS:
            kb.button(text=f"Подписаться на {ch}", url=f"https://t.me/{ch.replace('@','')}")
        return await message.answer("❌ <b>Подпишись на каналы, чтобы играть!</b>", reply_markup=kb.adjust(1).as_markup())
    
    # 2. Проверка Кулдауна (АНТИ-СПАМ)
    is_vip, _ = get_vip_info(user_id)
    limit = 7200 if is_vip else 14400 
    now = time.time()

    if user_id in cooldowns:
        rem = int(limit - (now - cooldowns[user_id]))
        if rem > 0:
            return await message.reply(f"⏳ Кулдаун! Жди {rem//3600}ч. {(rem%3600)//60}мин.")

    # 3. Мгновенная установка КД
    cooldowns[user_id] = now
    
    card = get_card()
    if not card:
        del cooldowns[user_id]
        return await message.reply("⚠️ База карт пуста.")

    # 4. Анимация и выдача
    status_msg = await message.answer("🔄 Подготовка...")
    await animate_card_opening(status_msg, card)
    
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
        conn.commit()
    except Exception as e:
        del cooldowns[user_id]
        return await message.answer("Ошибка сохранения данных.")
    finally: 
        cur.close()
        conn.close()
    
    cap = f"<b>КАРТА 🎉</b>\n\n👤 {html.escape(card['name'])}\n📊 {card['rating']}\n🛡 {html.escape(card['club'])}\n💰 +{reward} ⭐"
    await message.reply_photo(photo=card['photo_id'], caption=cap)

@dp.message(F.text == "Магазин 🛒")
async def open_shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze (4к)", callback_data="buy_bronze")
    kb.button(text="📦 Gold (5.7к)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant (7к)", callback_data="buy_brilliant")
    kb.button(text=f"⚡️ VIP 24ч ({VIP_PRICE}⭐)", callback_data="buy_vip")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин паков и статусов</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        u = cur.fetchone()
        
        if action == "vip":
            is_v, _ = get_vip_info(user_id)
            if is_v: return await callback.answer("VIP уже активен!", show_alert=True)
            if u['balance'] < VIP_PRICE: return await callback.answer("Недостаточно звезд!", show_alert=True)
            exp = get_now_msk() + timedelta(hours=24)
            cur.execute("UPDATE users SET balance = balance - %s, vip_until = %s WHERE user_id = %s", (VIP_PRICE, exp, user_id))
            conn.commit()
            await callback.message.answer(f"🚀 <b>VIP активирован на 24 часа!</b>")
        else:
            prices = {"bronze": 4000, "gold": 5700, "brilliant": 7000}
            cost = prices[action]
            if u['balance'] < cost: return await callback.answer("Недостаточно звезд!", show_alert=True)
            
            card = get_card(action)
            if not card: return await callback.answer("Ошибка базы.", show_alert=True)
            
            await animate_card_opening(callback.message, card)
            
            reward = get_stars_by_rating(card['rating'])
            cur.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (cost, reward, user_id))
            cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
            conn.commit()
            await callback.message.answer_photo(photo=card['photo_id'], caption=f"📦 <b>Пак открыт!</b>\n\n👤 {card['name']}\n📊 {card['rating']}\n💰 Кэшбек: +{reward} ⭐")
    finally:
        cur.close(); conn.close()
    await callback.answer()

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance, vip_until FROM users WHERE user_id=%s", (message.from_user.id,))
        u = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
        cnt = cur.fetchone()[0]
        is_v, _ = get_vip_info(message.from_user.id)
        v_st = "✅" if is_v else "❌"
        await message.reply(f"👤 <b>@{message.from_user.username}</b>\n💰 Баланс: <b>{u['balance'] if u else 0}</b> ⭐\n🗂 Карт: <b>{cnt}</b>\n⚡️ VIP: <b>{v_st}</b>")
    finally: cur.close(); conn.close()

@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="🥅 Пенальти (x2)", callback_data="game_penalty")
    await message.answer("🎯 <b>Выберите игру:</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "game_penalty")
async def penalty_ask_bet(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in penalty_cooldowns and time.time() - penalty_cooldowns[user_id] < 3600:
        rem = int(3600 - (time.time() - penalty_cooldowns[user_id]))
        return await callback.answer(f"⏳ КД! {rem // 60} мин.", show_alert=True)
    waiting_for_bet[user_id] = True
    await callback.message.edit_text("💰 <b>Введите сумму ставки (1к - 100к):</b>")

@dp.message(lambda message: waiting_for_bet.get(message.from_user.id))
async def penalty_process_bet(message: types.Message):
    user_id = message.from_user.id
    if not message.text.isdigit(): return
    bet = int(message.text)
    if bet < 1000 or bet > 100000: return await message.answer("❌ Лимит 1к - 100к.")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        u = cur.fetchone()
        if not u or u['balance'] < bet:
            waiting_for_bet.pop(user_id, None)
            return await message.answer("❌ Недостаточно ⭐")
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user_id))
        conn.commit()
    finally: cur.close(); conn.close()
    
    waiting_for_bet.pop(user_id, None)
    kb = InlineKeyboardBuilder()
    kb.button(text="Лево ⬅️", callback_data=f"kick_L_{bet}")
    kb.button(text="Центр ⬆️", callback_data=f"kick_C_{bet}")
    kb.button(text="Право ➡️", callback_data=f"kick_R_{bet}")
    await message.answer(f"🥅 <b>Ставка {bet} ⭐. Куда бьем?</b>", reply_markup=kb.adjust(3).as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def penalty_result(callback: types.CallbackQuery):
    data = callback.data.split("_")
    side, bet = data[1], int(data[2])
    gk_covers = random.sample(["L", "C", "R"], 2)
    penalty_cooldowns[callback.from_user.id] = time.time() 
    
    if side in gk_covers: 
        res = f"❌ <b>ВРАТАРЬ ОТБИЛ!</b> Ставка потеряна."
    else:
        win = bet * 2
        res = f"⚽️ <b>ГООООЛ! Ты выиграл {win} ⭐</b>"
        conn = get_db_connection(); cur = conn.cursor()
        try:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (win, callback.from_user.id))
            conn.commit()
        finally: cur.close(); conn.close()
    await callback.message.edit_text(res)

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
        top = cur.fetchall()
        await message.answer("📊 <b>Топ богатых игроков:</b>\n\n" + "\n".join([f"{i}. {u['username']} — {u['balance']}⭐" for i, u in enumerate(top, 1)]))
    finally: cur.close(); conn.close()

@dp.message(F.photo & (F.from_user.id == ADMIN_ID))
async def handle_photo(message: types.Message):
    temp_photo_buffer[ADMIN_ID] = max(message.photo, key=lambda p: p.file_size).file_id
    await message.reply("📸 Фото принято. Введи: `/add_player Имя, Рейтинг, Поз, Клуб` (через запятую)")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(ADMIN_ID)
    if not p_id: return await message.reply("❌ Сначала отправь фото!")
    try:
        args = message.text.replace("/add_player ", "").split(",")
        name, rat, pos, club = args[0].strip(), int(args[1].strip()), args[2].strip(), args[3].strip()
        rt = "legend" if rat >= 99 else "ivents" if rat >= 95 else "brilliant" if rat >= 90 else "gold" if rat >= 75 else "bronze"
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                     (name, rat, pos, rt.capitalize(), rt, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Игрок {name} успешно добавлен!"); del temp_photo_buffer[ADMIN_ID]
    except: await message.answer("❌ Ошибка! Формат: Имя, 90, ST, Real Madrid")

async def handle(request): return web.Response(text="Бот активен!")
async def start_webserver():
    app = web.Application(); app.router.add_get("/", handle)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT); await site.start()

async def main():
    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
