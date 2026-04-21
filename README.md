# LexGuard — Система анализа юридических документов

**Дипломная работа** — Егоров Н.Р., УрФУ, группа РИ-420944, 2026  
Направление: 09.03.04 Программная инженерия

## Технологический стек

| Компонент | Технология |
|---|---|
| LLM | Gemma3 (локально, Ollama) |
| Эмбеддинги | intfloat/multilingual-e5-base |
| Векторная БД | Qdrant |
| Backend | Python 3.11, FastAPI |
| Frontend | HTML/CSS/JS (без фреймворков) |
| Веб-сервер | Nginx |
| Оркестрация | Docker Compose |

## Быстрый старт

### Требования
- Docker Desktop (macOS, Linux, Windows)
- 8+ ГБ оперативной памяти
- 10+ ГБ свободного места на диске

### Запуск

```bash
# 1. Клонируй или распакуй проект
cd lexguard

# 2. Запусти весь стек одной командой
docker compose up -d

# 3. Дождись загрузки модели Gemma3 (~3-5 минут при первом запуске)
docker logs lexguard-ollama-init -f

# 4. Открой приложение
open http://localhost:3000
```

### Проверка статуса

```bash
# Статус всех контейнеров
docker compose ps

# API статус
curl http://localhost:8000/health

# Статус модели и RAG
curl http://localhost:8000/api/v1/status
```

## Структура проекта

```
lexguard/
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── main.py              # FastAPI приложение
│   ├── requirements.txt
│   ├── data/
│   │   └── legal_norms.json # Расширенная база нормативных шаблонов (~294 норм)
│   ├── api/
│   │   └── routes.py        # REST API эндпоинты
│   ├── models/
│   │   └── schemas.py       # Pydantic схемы
│   └── services/
│       ├── preprocessor.py  # Извлечение и сегментация текста
│       ├── rag.py           # Векторный RAG (Qdrant + e5)
│       └── analyzer.py      # Анализ через Gemma3
├── frontend/
│   ├── Dockerfile
│   └── index.html           # SPA интерфейс
└── nginx/
    └── default.conf         # Реверс-прокси
```

## API

| Метод | Endpoint | Описание |
|---|---|---|
| POST | `/api/v1/analyze` | Загрузить и проанализировать договор |
| GET | `/api/v1/analyze/{id}` | Получить результат по ID |
| GET | `/api/v1/analyze/{id}/grouped` | Получить риски, сгруппированные по категориям |
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

## База норм и контроль качества

```bash
# Сгенерировать расширенную базу legal_norms.json
python backend/scripts/generate_extended_legal_norms.py

# Провалидировать схему и качество норм
python backend/scripts/validate_legal_norms.py
```

## Остановка

```bash
docker compose down          # остановить контейнеры
docker compose down -v       # остановить и удалить данные
```

## Архитектура системы

```
Пользователь
    │ PDF/DOCX
    ▼
[Nginx :3000]
    │
    ├── / → Frontend (HTML/CSS/JS)
    │
    └── /api/ → [FastAPI :8000]
                    │
                    ├── PreprocessorService
                    │   └── Сегментация текста
                    │
                    ├── RAGService
                    │   ├── multilingual-e5-base (эмбеддинги)
                    │   └── Qdrant (векторный поиск)
                    │
                    └── AnalyzerService
                        └── Gemma3 via Ollama :11434
```
