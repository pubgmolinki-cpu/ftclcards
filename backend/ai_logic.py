import os
import json
import re
from datetime import datetime, timedelta
import groq

# Подтягиваем API-ключ из переменных окружения сайта
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Инициализируем клиента Groq
client = groq.Groq(api_key=GROQ_API_KEY)

def calculate_odds(team1_name, team1_squad, team2_name, team2_squad):
    """
    Анализирует составы и рейтинги через ИИ Groq и возвращает 
    коэффициенты с учетом букмекерской маржи.
    """
    if not GROQ_API_KEY:
        print("Ошибка: GROQ_API_KEY не установлен в переменных окружения!")
        return None

    prompt = f"""
    Ты — продвинутый аналитик футбольных рейтингов. Твоя задача — рассчитать коэффициенты для ставок.
    
    Команда 1: {team1_name}
    Состав и рейтинги: {team1_squad}
    
    Команда 2: {team2_name}
    Состав и рейтинги: {team2_squad}
    
    Инструкция:
    1. Сравни суммарную силу составов.
    2. Рассчитай вероятность Победы 1 (P1), Ничьи (X) и Победы 2 (P2). Сумма = 1.0.
    3. Рассчитай десятичные коэффициенты: K = 1 / P.
    4. Примени маржу 10% (умножь коэффициенты на 0.9).
    
    Верни СТРОГО JSON-объект следующего вида:
    {{
        "k_p1": 1.85,
        "k_x": 3.40,
        "k_p2": 2.15,
        "winner_prediction": "Название команды",
        "confidence": "85%"
    }}
    """

    try:
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        # Парсим результат
        odds_data = json.loads(completion.choices[0].message.content)
        return odds_data
    except Exception as e:
        print(f"Ошибка при запросе к Groq: {e}")
        return None

def parse_admin_text(text):
    """
    Парсит твое сообщение из телеграма.
    Формат: Добавить матч: Команда1 (Игрок-80, Игрок-75) vs Команда2 (Игрок-90, Игрок-60)
    """
    pattern = r"Добавить матч: (.+?) \((.+?)\) vs (.+?) \((.+?)\)"
    match = re.search(pattern, text)
    if match:
        return {
            "t1": match.group(1),
            "s1": match.group(2),
            "t2": match.group(3),
            "s2": match.group(4)
        }
    return None

def get_deadline():
    """
    Авто-дедлайн: 21:00 завтрашнего дня.
    """
    now = datetime.now()
    deadline = now + timedelta(days=1)
    return deadline.replace(hour=21, minute=0, second=0, microsecond=0)
