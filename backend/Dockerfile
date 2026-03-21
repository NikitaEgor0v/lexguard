FROM python:3.11-slim

WORKDIR /app

# Системные зависимости для pdfplumber и torch
RUN apt-get update && apt-get install -y \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Предзагружаем модель эмбеддингов при сборке образа
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-base')"

COPY . .

RUN touch api/__init__.py models/__init__.py services/__init__.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
