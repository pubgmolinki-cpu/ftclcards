#!/bin/bash
# Запускаем бота в фоновом режиме
python backend/bot.py &
# Запускаем FastAPI
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
