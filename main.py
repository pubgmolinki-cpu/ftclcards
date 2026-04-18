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

# Временные хранилища
waiting_for_bet = {} 
user_bets = {}
user_cooldowns = {} # {uid: {"pnl": ts, "guess": ts, "pack": ts}}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def send_admin_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

# --- ОБЯЗАТЕЛЬНАЯ ПОДПИСКА (КНОПКИ-ССЫЛКИ) ---
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
    ref_id = message.text.split()[1] if len(message.text.split()) > 1 else None
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username, referrer_id) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                (uid, message.from_user.username, ref_id))
    
    if ref_id and ref_id.isdigit() and int(ref_id) != uid:
        cur.execute("UPDATE users SET balance = balance + 5000 WHERE user_id = %s", (int(ref_id),))
    
    conn.commit(); cur.close(); conn.close()

    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПОЛУЧЕНИЕ КАРТЫ (ПО ШАБЛОНУ) ---
@dp.message(F.text == "Получить Карту 🏆")
async def get_card(message: types.Message):
    uid = message.from_user.id
    
    # Проверка подписки с кнопками
    not_sub = await get_not_subscribed_channels(uid)
    if not_sub:
        kb = InlineKeyboardBuilder()
        for i, (name, url) in enumerate(not_sub, 1):
            kb.button(text=f"Канал {i} 📢", url=url)
        kb.button(text="Я подписался ✅", callback_data="check_subs")
        return await message.answer("❌ <b>Подпишись на каналы!</b>", reply_markup=kb.adjust(1).as_markup())

    # КД 4 часа
    now = time.time()
    last_pack = user_cooldowns.get(uid, {}).get("pack", 0)
    if now - last_pack < 14400:
        rem = int(14400 - (now - last_pack))
        return await message.answer(f"⌛ <b>Жди {rem//3600}ч. {(rem%3600)//60}м.</b>")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    
    # Анимация
    st = await message.answer("Открываем пак... 💼")
    await asyncio.sleep(1); await st.edit_text(f"Позиция: <b>{card['position']}</b>")
    await asyncio.sleep(1); await st.delete()

    if uid not in user_cooldowns: user_cooldowns[uid] = {}
    user_cooldowns[uid]["pack"] = now
    
    cur.execute("UPDATE users SET balance = balance + 1250 WHERE user_id = %s", (uid,))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()

    # ШАБЛОН СО СКРИНШОТА
    caption = (
        f"🎉 <b>ВАМ ВЫПАЛА НОВАЯ КАРТА!</b> 🎉\n\n"
        f"👤 <b>{card['name'].upper()}</b>\n"
        f"📊 <b>Рейтинг:{card['rating']}</b>\n"
        f"🛡 <b>Клуб:{card['club']}</b>\n"
        f"💰 <b>+1250 ⭐</b>"
    )
    await message.answer_photo(card['photo_id'], caption=caption)
    await send_admin_log(f"👤 @{message.from_user.username} выбил {card['name']}")

# --- МИНИ-ИГРЫ (СТАВКИ + КД) ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (КД 1ч)", callback_data="game_pnl")
    kb.button(text="🧩 Угадай игрока (КД 2ч)", callback_data="game_guess")
    kb.button(text="⚔️ PvP Матч", callback_data="game_pvp")
    await message.answer("🎮 <b>Выберите игру:</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("game_"))
async def start_game(call: types.CallbackQuery):
    uid = call.from_user.id
    g_type = call.data.split("_")[1]
    
    # Проверка КД
    cd = 3600 if g_type == "pnl" else 7200
    now = time.time()
    if now - user_cooldowns.get(uid, {}).get(g_type, 0) < cd:
        rem = int(cd - (now - user_cooldowns.get(uid, {}).get(g_type, 0)))
        return await call.answer(f"⏳ КД! Жди {rem//60} мин.", show_alert=True)

    waiting_for_bet[uid] = g_type
    await call.message.edit_text("💰 <b>Введите сумму вашей ставки:</b>")

@dp.message(lambda msg: msg.from_user.id in waiting_for_bet)
async def process_bet(message: types.Message):
    uid = message.from_user.id
    g_type = waiting_for_bet.pop(uid)
    if not message.text.isdigit(): return await message.answer("❌ Числом!")
    
    bet = int(message.text)
    user_bets[uid] = {"bet": bet, "game": g_type}
    
    if g_type == "pnl":
        kb = InlineKeyboardBuilder()
        kb.button(text="Лево ⬅️", callback_data="k_l"); kb.button(text="Центр ⬆️", callback_data="k_c"); kb.button(text="Право ➡️", callback_data="k_r")
        await message.answer(f"⚽ Ставка {bet} принята! Куда бьешь?", reply_markup=kb.as_markup())
    elif g_type == "guess":
        # Логика угадайки (4 кнопки)
        await message.answer(f"🧩 Угадайка за {bet} запущена...") # (тут код генерации 4 кнопок)

@dp.callback_query(F.data.startswith("k_"))
async def res_pnl(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid not in user_bets: return await call.answer("Ставка не найдена")
    bet = user_bets.pop(uid)['bet']
    win = random.choice([True, False])
    
    if uid not in user_cooldowns: user_cooldowns[uid] = {}
    user_cooldowns[uid]["pnl"] = time.time()
    
    conn = get_db_connection(); cur = conn.cursor()
    if win:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, uid))
        await call.message.edit_text(f"✅ <b>ГОООЛ!</b> +{bet*2} ⭐")
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
        await call.message.edit_text(f"❌ <b>СЕЙВ!</b> -{bet} ⭐")
    conn.commit(); cur.close(); conn.close()

# --- ОСТАЛЬНЫЕ КНОПКИ ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    kb = InlineKeyboardBuilder().button(text="💼 Моя коллекция", callback_data="v_coll")
    await message.answer(f"👤 <b>Профиль</b>\n💰 Баланс: {u['balance']:,} ⭐", reply_markup=kb.as_markup())

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    txt = "🏆 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]:,} ⭐" for i, r in enumerate(cur.fetchall())])
    await message.answer(txt)

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎫 Обычный (2.5k)", callback_data="buy_2500")
    kb.button(text="💎 Элитный (15k)", callback_data="buy_15000")
    await message.answer("🛒 <b>Магазин FTCL</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pk(call: types.CallbackQuery):
    price = int(call.data.split("_")[1])
    # (Код списания баланса и выдачи карты...)
    await call.answer("Покупка совершена!")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
