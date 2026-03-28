import asyncio, psycopg2, os, html, random, time
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

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
cooldowns = {} 
temp_photo_buffer = {}
duels = {} # Хранилище активных игр

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# --- АНТИ-СОН ---
async def handle(request):
    return web.Response(text="Bot is running! ⚽️")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user_by_username(username):
    username = username.replace("@", "").lower()
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT user_id, username FROM users WHERE LOWER(username) = %s", (username,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res

def get_card(rarity_filter=None):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
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
    finally: cur.close(); conn.close()

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    uname = message.from_user.username or f"user_{user_id}"
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (user_id, uname))
    conn.commit(); cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Магазин 🛒")
    kb.button(text="Профиль 👤"); kb.button(text="Дуэль 🔫")
    kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 1)
    await message.answer("⚽️ <b>FTCL Cards: Дуэли включены!</b>", reply_markup=kb.as_markup(resize_keyboard=True))

# --- ЛОГИКА ДУЭЛЕЙ ---

@dp.message(F.text == "Дуэль 🔫")
async def duel_main(message: types.Message):
    await message.answer("🚀 <b>Режим Дуэли</b>\nВведите username игрока, которого хотите вызвать (без @):")

@dp.message(lambda m: m.text and not m.text.startswith("/") and len(m.text.split()) == 1 and not m.reply_to_message)
async def invite_duel(message: types.Message):
    target = get_user_by_username(message.text)
    if not target: return await message.reply("❌ Игрок не найден в базе.")
    if target['user_id'] == message.from_user.id: return await message.reply("❌ Нельзя играть с самим собой.")
    
    duel_id = f"{message.from_user.id}_{target['user_id']}"
    duels[duel_id] = {'p1': message.from_user.id, 'p2': target['user_id'], 'p1_name': message.from_user.first_name, 'status': 'wait'}
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Принять ✅", callback_data=f"d_acc_{duel_id}")
    kb.button(text="Отказ ❌", callback_data=f"d_dec_{duel_id}")
    await bot.send_message(target['user_id'], f"⚔️ <b>Вызов!</b>\nИгрок {message.from_user.first_name} вызывает вас на дуэль 3х3!", reply_markup=kb.as_markup())
    await message.answer("📨 Вызов отправлен...")

@dp.callback_query(F.data.startswith("d_acc_"))
async def duel_accept(callback: types.CallbackQuery):
    duel_id = callback.data.split("_", 2)[2]
    d = duels.get(duel_id)
    if not d: return await callback.answer("Дуэль не найдена.")
    
    kb = InlineKeyboardBuilder()
    for r in ["Bronze", "Gold", "Brilliant"]:
        kb.button(text=r, callback_data=f"d_rare_{duel_id}_{r.lower()}")
    await callback.message.edit_text("Выберите редкость карты для ставки:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("d_rare_"))
async def duel_set_rare(callback: types.CallbackQuery):
    _, _, duel_id, rarity = callback.data.split("_")
    d = duels[duel_id]
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT uc.id FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s AND c.rarity_type = %s LIMIT 1", (d['p1'], rarity))
    c1 = cur.fetchone()
    cur.execute("SELECT uc.id FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s AND c.rarity_type = %s LIMIT 1", (d['p2'], rarity))
    c2 = cur.fetchone()
    
    if not c1 or not c2:
        cur.close(); conn.close()
        return await callback.answer(f"❌ У кого-то нет карт редкости {rarity}!", show_alert=True)
    
    d.update({'rarity': rarity, 'p1_card': c1['id'], 'p2_card': c2['id'], 'p1_s': 0, 'p2_s': 0, 'turn': d['p1']})
    cur.close(); conn.close()
    await callback.message.delete()
    await start_duel_field(d['p1'], duel_id)

async def start_duel_field(uid, duel_id):
    d = duels[duel_id]
    d['bombs'] = random.sample(range(9), 3)
    d['open'] = []
    
    kb = InlineKeyboardBuilder()
    for i in range(9): kb.button(text="❓", callback_data=f"d_hit_{duel_id}_{i}")
    kb.adjust(3)
    await bot.send_message(uid, "🎮 <b>Твой ход!</b>\nИщи мячи ⚽️, избегай бомб 💣", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("d_hit_"))
async def duel_hit(callback: types.CallbackQuery):
    _, _, duel_id, cell = callback.data.split("_")
    cell, d = int(cell), duels.get(duel_id)
    if not d or callback.from_user.id != d['turn']: return await callback.answer("Не твой ход!")

    if cell in d['bombs']:
        await callback.message.edit_text("💣 <b>БАБАХ!</b> Вы подорвались.")
        if d['turn'] == d['p1']:
            d['turn'] = d['p2']
            await bot.send_message(d['p2'], "Соперник взорвался! Теперь твоя очередь.")
            await start_duel_field(d['p2'], duel_id)
        else:
            await finish_duel(duel_id)
    else:
        score_key = 'p1_s' if d['turn'] == d['p1'] else 'p2_s'
        d[score_key] += 1
        d['open'].append(cell)
        kb = InlineKeyboardBuilder()
        for i in range(9):
            if i in d['open']: kb.button(text="⚽️", callback_data="none")
            else: kb.button(text="❓", callback_data=f"d_hit_{duel_id}_{i}")
        kb.adjust(3)
        await callback.message.edit_reply_markup(reply_markup=kb.as_markup())

async def finish_duel(duel_id):
    d = duels[duel_id]
    s1, s2 = d['p1_s'], d['p2_s']
    win_text = f"🏁 <b>Результаты дуэли:</b>\nИгрок 1: {s1} ⚽️\nИгрок 2: {s2} ⚽️\n\n"
    
    conn = get_db_connection(); cur = conn.cursor()
    if s1 > s2:
        cur.execute("UPDATE user_cards SET user_id = %s WHERE id = %s", (d['p1'], d['p2_card']))
        win_text += f"🏆 Победил P1! Он забирает карту соперника."
    elif s2 > s1:
        cur.execute("UPDATE user_cards SET user_id = %s WHERE id = %s", (d['p2'], d['p1_card']))
        win_text += f"🏆 Победил P2! Он забирает карту соперника."
    else: win_text += "🤝 Ничья! Все при своих."
    conn.commit(); cur.close(); conn.close()
    
    for uid in [d['p1'], d['p2']]: await bot.send_message(uid, win_text)
    del duels[duel_id]

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (Профиль, Получение карт и т.д.) ---

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    if user_id in cooldowns and now - cooldowns[user_id] < 28800:
        rem = int(28800 - (now - cooldowns[user_id]))
        return await message.reply(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}мин.")
    
    card = get_card()
    if not card: return await message.reply("База пуста.")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
    conn.commit(); cur.close(); conn.close()
    cooldowns[user_id] = now
    await message.reply_photo(photo=card['photo_id'], caption=f"👤 <b>{card['name']}</b>\n✨ {card['rarity']}")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    cur.close(); conn.close()
    await message.reply(f"👤 <b>Профиль</b>\nНик: @{message.from_user.username}\nКарт в коллекции: {cnt}")

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
