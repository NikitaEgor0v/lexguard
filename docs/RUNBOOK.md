# LexGuard — Серверный Runbook

Пошаговая инструкция для production-запуска LexGuard.

**Время:** 15–25 минут
**Требования:** Docker, Docker Compose, 8GB+ RAM (16GB+ рекомендуется для qwen2.5:7b)

---

## Быстрый старт

```bash
cd lexguard

# Настроить модель
echo "LLM_MODEL=qwen2.5:7b" > .env

# Запустить всё
docker compose up -d

# Подождать загрузку модели
docker logs -f lexguard-ollama-init

# Проверить
curl http://localhost:8000/health

# Открыть UI
open http://localhost:3000
```

---

## Детальная инструкция

### Шаг 1: Подготовка (2 мин)

```bash
docker --version        # >= 24.0
docker compose version  # >= 2.20
cd /path/to/lexguard
```

### Шаг 2: Конфигурация (.env)

��оздайте `.env` в корне проекта:

```bash
# --- Модель ---
LLM_MODEL=qwen2.5:7b

# --- Таймауты (опционально) ---
LLM_REQUEST_TIMEOUT=300
LLM_HEARTBEAT_TIMEOUT=600

# --- RAG (опцио��ально) ---
MIN_RELEVANCE_SCORE=0.50
MAX_CHUNKS_PER_SEGMENT=3
```

**Доступные модели:**
| Модель | VRAM | Скорость | Когда использовать |
|--------|------|----------|-------------------|
| `gemma2:2b` | 4GB | Быстро | Локальная разработка |
| `gemma3:4b` | 8GB | Средне | Fallback |
| `qwen2.5:7b` | 16GB | Средне | Production (рекомендуется) |

### Шаг 3: Запуск (3 мин)

```bash
docker compose up -d
docker compose ps
```

Ожидаемый вывод:
```
NAME                  STATUS
lexguard-backend      Up
lexguard-frontend     Up
lexguard-ollama       Up (healthy)
lexguard-ollama-init  Exited (0)
lexguard_celery       Up
lexguard_postgres     Up (healthy)
lexguard_redis        Up (healthy)
lexguard-qdrant       Up (healthy)
```

### Шаг 4: Загрузка модели (5-15 мин)

```bash
docker logs -f lexguard-ollama-init
```

Если модель не загружается автоматически:
```bash
docker exec -it lexguard-ollama ollama pull qwen2.5:7b
```

### Шаг 5: Прогрев модели (1 мин)

Первый запрос загружает модель в память (30-60 сек):
```bash
docker exec lexguard-ollama ollama run qwen2.5:7b "Привет"
```

### Шаг 6: Проверка системы

```bash
# Health check
curl http://localhost:8000/health
# → {"status": "healthy"}

# Полный статус
curl http://localhost:8000/api/v1/status
```

Ожидаемый ответ `/api/v1/status`:
```json
{
  "ollama": "running",
  "model": "qwen2.5:7b",
  "model_available": true,
  "model_config": {
    "max_segment_chars": 1000,
    "max_rag_chars": 1200,
    "max_rag_norms": 2,
    "request_timeout": 300,
    "heartbeat_timeout": 600
  },
  "rag": {
    "status": "ready",
    "norms_count": 43,
    "min_relevance_score": 0.5
  }
}
```

### Шаг 7: Миграции БД

Миграции применяются автоматически при старте backend (`start.sh` → `alembic upgrade head`). Для ручной проверки:

```bash
docker exec lexguard-backend alembic upgrade head
```

### Шаг 8: Контрольный анализ (5 мин)

1. Откройте `http://localhost:3000`
2. Зарегистрируйтесь / войдите
3. Загрузите небольшой договор (1-2 страницы)
4. Дождитесь завершения

**Критерии готовности:**
- Анализ завершился статусом "completed"
- Время < 5 минут для 10-15 сегментов
- Риски отображаются корректно
- AI-чат отвечает на вопросы

---

## Переключение модели

```bash
# 1. Остановить сервисы
docker compose stop backend celery_worker

# 2. Изменить модель в .env
echo "LLM_MODEL=gemma3:4b" > .env

# 3. Загрузить модель
docker exec -it lexguard-ollama ollama pull gemma3:4b

# 4. Перезапустить
docker compose up -d backend celery_worker

# 5. Прогреть
docker exec lexguard-ollama ollama run gemma3:4b "Тест"
```

---

## Мониторинг

### Логи

```bash
docker logs -f lexguard-backend       # API
docker logs -f lexguard_celery        # Анализ документов
docker logs -f lexguard-ollama        # LLM
```

### Прогресс анализа

```bash
# Через Redis
docker exec lexguard_redis redis-cli GET "progress:YOUR_ANALYSIS_ID"

# Через API
curl http://localhost:8000/api/v1/analyze/YOUR_ANALYSIS_ID
```

---

## Типичные проблемы

| Проблема | Решение |
|----------|---------|
| `model_available: false` | `docker exec lexguard-ollama ollama pull <model>` |
| Таймаут анализа | Увеличить `LLM_REQUEST_TIMEOUT` в .env |
| "Analysis interrupted" | Увеличить `LLM_HEARTBEAT_TIMEOUT` |
| OOM (Out of Memory) | Переключиться на модель меньшего размера |
| RAG не находит нормы | Уменьшить `MIN_RELEVANCE_SCORE` до 0.40 |
| 502 Bad Gateway | Подождать старт backend или перезапустить frontend |

---

## ��ек-лист готовности

- [ ] Docker и Docker Compose установлены
- [ ] `.env` создан с нужной моделью
- [ ] Все контейнеры запущены
- [ ] Модель загружена и прогрета
- [ ] Health-check возвращает `healthy`
- [ ] Контроль��ый анализ пройден
