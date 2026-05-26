# LexGuard — Система анализа юридических документов

Интеллектуальная система анализа юридических документов.  
Выявляет юридические, финансовые и операционные риски в договорах (PDF, DOCX) с помощью LLM и RAG.

## Технологический стек

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

## Быстрый старт

### Требования
- Docker Desktop (macOS, Linux, Windows)
- 8+ ГБ оперативной памяти (16+ ГБ рекомендуется для qwen3:8b)
- 10+ ГБ свободного места на диске

### Запуск

```bash
cd lexguard

# Настроить модель
echo "LLM_MODEL=qwen3:8b" > .env

# Запустить весь стек
docker compose up -d

# Дождаться загрузки модели (~5-15 минут при первом запуске)
docker logs -f lexguard-ollama-init

# Открыть приложение
open http://localhost:3000
```

### Проверка статуса

```bash
# Статус всех контейнеров
docker compose ps

# Health check
curl http://localhost:8000/health

# Полный статус (модель, RAG, конфигурация)
curl http://localhost:8000/api/v1/status
```

## Поддерживаемые модели

| Модель | VRAM | Рекомендация |
|--------|------|--------------|
| `gemma2:2b` | 4 ГБ | Локальная разработка (быстро) |
| `gemma3:4b` | 8 ГБ | Fallback на сервере |
| `qwen3:8b` | 16 ГБ | Production (рекомендуется) |

Модель задаётся переменной `LLM_MODEL` в `.env`. Адаптивные лимиты (размер сегмента, объём RAG-контекста) определяются автоматически через `config/model_registry.py`.

## Структура проекта

```
lexguard/
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── main.py                # FastAPI приложение
│   ├── requirements.txt
│   ├── config/
│   │   └── model_registry.py  # Адаптивная конфигурация моделей
│   ├── data/
│   │   └── legal_norms.json   # База нормативных шаблонов
│   ├── api/
│   │   ├── routes.py          # REST API эндпоинты
│   │   ├── chat_routes.py     # AI-чат по результатам анализа
│   │   └── auth_routes.py     # JWT-аутентификация
│   ├── models/
│   │   └── schemas.py         # Pydantic схемы
│   └── services/
│       ├── preprocessor.py    # Извлечение и сегментация текста
│       ├── rag.py             # Векторный RAG (Qdrant + e5)
│       ├── analyzer.py        # Анализ через LLM
│       ├── chat_service.py    # AI-чат
│       └── executive_summary.py
├── frontend/
│   ├── Dockerfile
│   └── index.html             # SPA интерфейс
├── nginx/
│   └── default.conf           # Реверс-прокси
└── docs/                      # Техническая документация
```

## API

| Метод | Endpoint | Описание |
|---|---|---|
| POST | `/api/v1/analyze` | Загрузить и проанализировать договор |
| GET | `/api/v1/analyze/{id}` | Получить результат по ID |
| GET | `/api/v1/analyze/{id}/grouped` | Риски, сгруппированные по категориям |
| GET | `/api/v1/status` | Статус системы (Ollama, RAG) |
| GET | `/health` | Healthcheck |

### Пример запроса

```bash
curl -X POST http://localhost:3000/api/v1/analyze \
  -F "file=@contract.pdf"
```

### Пример ответа

```json
{
  "analysis_id": "uuid",
  "filename": "contract.pdf",
  "status": "completed",
  "executive_summary": "Договор классифицирован как высокорисковый...",
  "summary": {
    "total_segments": 14,
    "risky_segments": 6,
    "high_risk_count": 2,
    "medium_risk_count": 3,
    "low_risk_count": 1,
    "risk_score": 0.38
  },
  "risks": [
    {
      "segment_id": 3,
      "text": "Штраф определяется по усмотрению заказчика...",
      "is_risky": true,
      "risk_level": "high",
      "risk_category": "финансовый",
      "risk_description": "Штраф без фиксированного размера — неограниченный финансовый риск",
      "recommendation": "Заменить на фиксированный процент: 0,1% от стоимости этапа за каждый день"
    }
  ]
}
```

## Конфигурация

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `LLM_MODEL` | Модель Ollama | `gemma2:2b` |
| `OLLAMA_URL` | URL Ollama API | `http://ollama:11434` |
| `LLM_REQUEST_TIMEOUT` | Таймаут запроса к Ollama (сек) | `300` |
| `MIN_RELEVANCE_SCORE` | Порог отсечения RAG (0.0–1.0) | `0.50` |
| `MAX_CHUNKS_PER_SEGMENT` | Максимум RAG-чанков на сегмент | `3` |
| `MAX_SEGMENTS_PER_DOCUMENT` | Лимит сегментов (0 = без лимита) | `500` |

Полный список переменных — в `.env.example`.

## Остановка

```bash
docker compose down          # остановить контейнеры
docker compose down -v       # остановить и удалить данные
```

## Архитектура

```
Пользователь
    │ PDF/DOCX
    ▼
[Nginx :3000]
    │
    ├── / → Frontend (Vanilla JS)
    │
    └── /api/ → [FastAPI :8000]
                    │
                    ├── PreprocessorService → Сегментация текста
                    │
                    ├── Celery Worker
                    │   ├── RAGService (Qdrant + e5)
                    │   └── AnalyzerService (Ollama LLM)
                    │
                    ├── PostgreSQL → Результаты, пользователи, чат
                    └── Redis → Очередь задач, прогресс
```

## Документация

Подробная техническая документация — в папке [`docs/`](docs/README.md).
