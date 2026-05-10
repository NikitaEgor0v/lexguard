# Архитектура системы LexGuard

## 1. Обзор

**LexGuard** — интеллектуальная система автоматизированного юридического ана��иза контрактов. Выявляет юридические, финансовые и операционные риски в текстах договоров (PDF, DOCX) с использованием LLM и RAG.

Система построена на микросервисной архитектуре и оркестрируется Docker Compose.

---

## 2. Компоненты

### Frontend (Nginx + Vanilla JS)
Реактивный пользовательский интерфейс. Взаимодействует с бэкендом через REST API, использует периодический polling для потокового отображения прогресса анализа.

Файлы: `frontend/js/` — `analysis.js`, `api.js`, `app.js`, `auth.js`, `chat.js`, `documents.js`, `history.js`, `upload.js`, `theme.js`.

### Backend (FastAPI)
Ядро системы. HTTP-запросы, JWT-аутентификация, управление БД и маршрутизация задач в Celery.

Ключевые сервисы (`backend/services/`):
- `analyzer.py` — основной цикл анализа, промпты, парсинг JSON
- `rag.py` — векторный поиск, фильтрация, пользовательские эталон��
- `preprocessor.py` — сегментация текста
- `chat_service.py` — AI-чат по результатам анализа
- `chat_context_builder.py` — сборка промпта чата
- `document_service.py` — загрузка и векторизация пользовательских эталонов
- `executive_summary.py` — генерация Executive Summary
- `risk_grouping.py` — группировка рисков по категориям

### Celery Worker + Redis
Асинхронный контур. FastAPI мгновенно возвращает `analysis_id`, Celery в фоне порционно обрабатывает документ. Redis — брокер сообщений и хранилище прогресса (`progress:{analysis_id}`).

### PostgreSQL
Хранилище бизнес-логики: пользователи, история анализов, риск-отчёты, чат-сессии. Миграции через Alembic.

### Qdrant
Векторная БД. Хранит эмбеддинги системных правовых норм (коллекция `legal_norms`) и пользовательских эталонов (коллекция `user_documents`). Метрика: Cosine, размерность: 768.

### Ollama
Контейнер для LLM. По умолчанию — модель из переменной `LLM_MODEL` (рекомендуется `qwen2.5:7b`). Изолирован от бэкенда для квотирования ресурсов.

---

## 3. Поток данных (Data Flow)

```
Upload → FastAPI → PreprocessorService (сегментация)
  → Celery Queue → Redis (статус/heartbeat)
  → Последовательный цикл:
      [ Qdrant Vector Search (system + user docs) → Ollama RAG Generation → JSON Parse → Batch Buffer ]
  → PostgreSQL Save (каждые ANALYSIS_BATCH_SIZE=20 сегментов)
  → Финализация (summary + executive_summary)
  → Frontend (polling /analyze/{id}/grouped)
```

**Режим обработки:** Сегменты анализируются последовательно (один за другим). GPU получает все ресурсы на каждый запрос.

**Инкрементальное сохранение:** Результаты сохраняются в PostgreSQL пакетами по 20 сегментов. Frontend подгружает риски по мере появления через `/analyze/{id}/grouped`, не дожидаясь завершения анализа. Executive Summary генерируется после обработки последнег�� сегмента.

---

## 4. А��аптивная конфигурация моделей

Конфигурация LLM хранится в `config/model_registry.py`. Лимиты применяются автоматически в runtime через `analyzer.py`:

| Модель | context_window | max_segment | max_rag | max_norms | compact_prompt |
|--------|----------------|-------------|---------|-----------|----------------|
| `gemma2:2b` | 2048 | 400 | 800 | 2 | да |
| `gemma3:4b` | 8192 | 800 | 1500 | 3 | нет |
| `qwen2.5:7b` | 4096 | 1000 | 1200 | 2 | нет |

**Поток применения:**
```
LLM_MODEL (env) → get_model_config() → ModelConfig → analyzer.py:
  - MAX_SEGMENT_CHARS = config.max_segment_chars
  - MAX_RAG_CONTEXT_CHARS = config.max_rag_chars
  - MAX_RAG_NORMS = config.max_rag_norms
  - payload.options.num_ctx = config.context_window
  - payload.options.num_predict = config.max_output
  - payload.options.temperature = config.temperature
```

---

## 5. Сегментация документов (PreprocessorService)

Алгоритм «безпотерьной» буферизации:
- Документ разбивается по нумерации параграфов или двойным абзацам
- Короткие пункты накапливаются в буфере до `TARGET_SEGMENT_LENGTH = 800` символов
- Максимальный размер сегмента: `MAX_SEGMENT_LENGTH = 1200` символов
- Минимальный размер: `MIN_SEGMENT_LENGTH = 150` символов
- Максимальное количество сегментов: `MAX_SEGMENTS_PER_DOCUMENT = 500` (0 = без ограничения)

---

## 6. Схема базы данных

PostgreSQL + SQLAlchemy 2.0 + Alembic.

| Таблица | Назначение |
|---------|-----------|
| `users` | Учётные данные, пароли (bcrypt) |
| `user_documents` | Метаданные пользовательских эталонов для RAG. Эмбеддинги — в Qdrant |
| `analysis_results` | Сводный скоринг анализа (score, counts, status) |
| `risk_items` | Детальная разбивка рисков: уровень, категория, safe_redaction |
| `chat_sessions` | История чат-сессий (паттерн Get-or-Create) |
| `chat_messages` | Соо��щения чата (user/assistant) |

**Ограничения целостности (миграция 007):**
- CHECK: `analysis_results.status` ∈ {processing, completed, failed}
- CHECK: `risk_items.risk_level` ∈ {high, medium, low, none}
- CHECK: `chat_messages.role` ∈ {user, assistant}
- UNIQUE: `(analysis_id, segment_id)` — предотвращает дубликаты

---

## 7. Безопасность

- **IDOR Protection**: Проверка владельца для всех эндпоинтов анализа и чата
- **JWT-аутентификация**: Токены для авторизации API-запросов
- **Heartbeat failure detection**: Анализы с устаревшим heartbeat автоматически помечаются как `failed`
- **404 для несуществующих ресурсов**: Вместо ложного `processing`

---

## 8. Отказоустойчивость

- **RAG fallback**: Если Qdrant недоступен, используется словарный метод на основе ключевых слов
- **Redis fallback**: Если Redis недоступен, прогресс игнорируется, анализ не падает
- **JSON parsing fallback**: При невалидном ответе LLM возвращается дефолтный `is_risky=True, risk_level=LOW`
- **Нейтральные сегменты**: Автоматическая классификация по regex-паттернам (цена, реквизиты, подписи)

---

## 9. Развёртывание

Проект полностью контейнеризирован (Docker Compose):

```bash
# Запуск
docker compose up -d --build

# Дождаться загрузки модели
docker logs -f lexguard-ollama-init

# Миграции (применяются автоматически при старте backend)
docker exec lexguard-backend alembic upgrade head

# Проверка
curl http://localhost:8000/health
# → {"status": "healthy"}
```

Подробнее: [RUNBOOK.md](RUNBOOK.md)
