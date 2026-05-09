FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для pdfplumber, torch, psycopg2 и утилита dos2unix
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev dos2unix \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Предзагружаем модель эмбеддингов при сборке образа
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"

COPY . .

RUN touch api/__init__.py models/__init__.py services/__init__.py config/__init__.py repositories/__init__.py

# Обрабатываем скрипт и запускаем
CMD dos2unix start.sh && chmod +x start.sh && bash start.sh
