# Техническая документация LexGuard

Добро пожаловать в раздел документации проекта **LexGuard** — интеллектуальной системы автоматизированного юридического анализа контрактов.

Этот раздел содержит актуальную инф��рмацию о внутренней архитектуре проекта, процессах машинного обучения, потоках данных и выявленных рисках. Документация предназначена для разработчиков, желающих восстановить контекст или продолжить развитие системы.

## Быстрый старт

```bash
# 1. Настроить модель
echo "LLM_MODEL=qwen3:8b" > .env

# 2. Запустить инфраструктуру
docker compose up -d

# 3. Дождаться загрузки модели
docker logs -f lexguard-ollama-init

# 4. Накатить миграции (обычно применяются автоматически при старте)
docker exec lexguard-backend alembic upgrade head

# 5. Открыть UI
open http://localhost:3000
```

## Поддерживаемые модели

| Модель | Context Window | Segment/RAG лимиты | Рекомендация |
|--------|---------------|---------------------|--------------|
| `gemma2:2b` | 2048 | 400/800 chars | Локальная разработка (быстро, 4GB VRAM) |
| `gemma3:4b` | 8192 | 800/1500 chars | Fallback на сервере (8GB VRAM) |
| `qwen2.5:7b` | 4096 | 1000/1200 chars | Средний вариант (16GB VRAM) |
| `qwen3:8b` | 8192 | 1200/2000 chars | Production (рекомендуемая, 16GB VRAM) |
| `qwen3:14b` | 16384 | 1500/3000 chars | Максимальное качество (24GB+ VRAM) |

Модель задается переменной `LLM_MODEL`. Все адаптивные лимиты (размер сегмента, объем RAG-контекста, количество норм) определяются автоматически через `config/model_registry.py`.

## Навигация по документации

- **[Архитектура системы (ARCHITECTURE.md)](ARCHITECTURE.md)**
  Общая структура проекта, взаимодействие компонентов (FastAPI, Nginx, PostgreSQL, Celery, Redis, Qdrant, Ollama) и схема базы данных.

- **[RAG и бизнес-логика (RAG_AND_LOGIC.md)](RAG_AND_LOGIC.md)**
  Векторный поиск в Qdrant, логика эталонных и пользовательских норм, пороговые значения, LLM-промпты и группировка рисков.

- **[API и потоки данных (API_AND_DATA_FLOW.md)](API_AND_DATA_FLOW.md)**
  Эндпоинты (загрузка, анализ, чат), схема обмена данными между клиентской частью и бэкендом (Celery + Redis polling).

- **[Краевые случаи и риски (EDGE_CASES_AND_RISKS.md)](EDGE_CASES_AND_RISKS.md)**
  Хрупкие места системы, хардкодные лимиты, фоллбеки. Что может пойти не так и как это решается.

- **[Схема правовых норм (LEGAL_NORMS_SCHEMA.md)](LEGAL_NORMS_SCHEMA.md)**
  Каноническая структура JSON-объекта для эталонной правовой нормы в RAG.

- **[Серверный Runbook (RUNBOOK.md)](RUNBOOK.md)**
  Пошаговая инструкция для production-запуска на сервере.

- **[История изменений (CHANGELOG.md)](CHANGELOG.md)**
  Журнал всех значимых изменений в проекте.

## Конфигурация через переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `LLM_MODEL` | Модель Ollama | `gemma2:2b` |
| `OLLAMA_URL` | URL Ollama API | `http://ollama:11434` |
| `LLM_REQUEST_TIMEOUT` | Таймаут HTTP-запроса к Ollama (сек) | `300` |
| `LLM_HEARTBEAT_TIMEOUT` | Таймаут heartbeat в Redis (сек) | `600` |
| `MIN_RELEVANCE_SCORE` | Порог отсечения RAG (0.0-1.0) | `0.50` (env) / `0.80` (код) |
| `MAX_CHUNKS_PER_SEGMENT` | Максимум RAG-чанков на сегмент | `3` |
| `ANALYSIS_BATCH_SIZE` | Размер пакета инкрементального сохранения | `20` |
| `MAX_SEGMENTS_PER_DOCUMENT` | Лимит сегментов на документ (0 = без лимита) | `500` |
| `LLM_MAX_WORKERS` | Параллельные Ollama workers | `2` |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL | `lexguard_dev` |

Полный список переменных см. в `.env.example` в корне проекта.

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Backend | FastAPI + SQLAlchemy 2.0 + Alembic |
| Async Tasks | Celery + Redis |
| Database | PostgreSQL 16 |
| Vector DB | Qdrant (cosine, 768d) |
| LLM | Ollama (qwen3:8b / gemma3:4b / gemma2:2b) |
| Embeddings | intfloat/multilingual-e5-base |
| Frontend | Vanilla JS + Nginx |
| Orchestration | Docker Compose |
