# LexGuard Server Runbook

Пошаговая инструкция для production-запуска LexGuard на сервере с моделью `llama3.1:8b` (основная) или `gemma3:4b` (fallback).

**Ожидаемое время:** 20–30 минут  
**Требования:** Docker, Docker Compose, 16GB+ RAM (24GB+ рекомендуется для 8B модели)

---

## Быстрый старт (TL;DR)

```bash
# 1. Клонировать и перейти
cd lexguard

# 2. Настроить модель
echo "LLM_MODEL=llama3.1:8b" > .env

# 3. Запустить инфраструктуру
docker compose up -d

# 4. Подождать загрузку модели (5-15 мин)
docker logs -f lexguard-ollama-init

# 5. Проверить статус
curl http://localhost:8000/api/v1/status

# 6. Накатить миграции
docker exec lexguard-backend alembic upgrade head

# 7. Открыть UI
open http://localhost:3000
```

---

## Детальная инструкция

### Шаг 1: Подготовка окружения (2 мин)

```bash
# Проверить версии
docker --version   # >= 24.0
docker compose version  # >= 2.20

# Перейти в директорию проекта
cd /path/to/lexguard
```

### Шаг 2: Конфигурация модели (1 мин)

Создайте файл `.env` в корне проекта:

```bash
# Основная модель для сервера
LLM_MODEL=llama3.1:8b

# Опционально: увеличить таймауты для большой модели
LLM_REQUEST_TIMEOUT=300
LLM_HEARTBEAT_TIMEOUT=600

# Опционально: настроить RAG
MIN_RELEVANCE_SCORE=0.50
```

**Альтернатива (fallback):** Если `llama3.1:8b` работает медленно:
```bash
LLM_MODEL=gemma3:4b
```

### Шаг 3: Запуск инфраструктуры (3 мин)

```bash
# Запустить все сервисы
docker compose up -d

# Проверить статус контейнеров
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
# Следить за загрузкой модели
docker logs -f lexguard-ollama-init
```

Ожидаемый вывод:
```
pulling manifest
pulling 8eeb52dfb3bb... 100%
verifying sha256 digest
writing manifest
success
Модель llama3.1:8b готова
```

**Если модель не загружается:**
```bash
# Загрузить вручную
docker exec -it lexguard-ollama ollama pull llama3.1:8b
```

### Шаг 5: Инициализация модели (2 мин)

Первый запрос к модели занимает 30-60 секунд, потому что модель загружается в память. Выполните контрольный запрос до приёма пользовательских документов:

```bash
# Контрольный запрос
docker exec lexguard-ollama ollama run llama3.1:8b "Привет, как дела?"
```

Ожидаемый результат: ответ модели в течение 10-60 сек.

### Шаг 6: Проверка системы (2 мин)

```bash
# Health check бэкенда
curl http://localhost:8000/health
# Ожидаемый ответ: {"status": "healthy"}

# Статус системы с моделью
curl http://localhost:8000/api/v1/status
```

Ожидаемый ответ:
```json
{
  "ollama": "running",
  "model": "llama3.1:8b",
  "model_available": true,
  "model_config": {
    "max_segment_chars": 1000,
    "max_rag_chars": 2000,
    "max_rag_norms": 4,
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

### Шаг 7: Накатить миграции БД (1 мин)

`backend` уже применяет миграции автоматически при старте контейнера (`alembic upgrade head` в `start.sh`).
Этот шаг нужен для ручной проверки или повторного применения миграций.

```bash
docker exec lexguard-backend alembic upgrade head
```

### Шаг 8: Проверка готовности анализа (5 мин)

1. Откройте `http://localhost:3000`
2. Загрузите контрольный договор (небольшой, 1-2 страницы)
3. Дождитесь завершения анализа

**Критерии готовности:**
- [ ] Анализ завершился статусом "completed" (не "failed")
- [ ] Время анализа < 5 минут для 10-15 сегментов
- [ ] Риски отображаются корректно

---

## Переключение на Fallback

Если `llama3.1:8b` работает слишком медленно (>2 мин на сегмент):

```bash
# 1. Остановить сервисы
docker compose stop backend celery_worker

# 2. Изменить модель
echo "LLM_MODEL=gemma3:4b" > .env

# 3. Загрузить fallback-модель
docker exec -it lexguard-ollama ollama pull gemma3:4b

# 4. Перезапустить
docker compose up -d backend celery_worker

# 5. Прогреть
docker exec lexguard-ollama ollama run gemma3:4b "Тест"
```

---

## Мониторинг и отладка

### Логи сервисов

```bash
# Бэкенд
docker logs -f lexguard-backend

# Celery worker (анализ документов)
docker logs -f lexguard_celery

# Ollama (LLM)
docker logs -f lexguard-ollama
```

### Проверка прогресса анализа

```bash
# Через Redis
docker exec lexguard_redis redis-cli GET "progress:YOUR_ANALYSIS_ID"

# Через API
curl http://localhost:8000/api/v1/analyze/YOUR_ANALYSIS_ID
```

### Типичные проблемы

| Проблема | Решение |
|----------|---------|
| `model_available: false` | `docker exec lexguard-ollama ollama pull llama3.1:8b` |
| Таймаут анализа | Увеличить `LLM_REQUEST_TIMEOUT` в .env |
| "Analysis interrupted" | Увеличить `LLM_HEARTBEAT_TIMEOUT` в .env |
| OOM (Out of Memory) | Переключиться на `gemma3:4b` |
| RAG не находит нормы | Уменьшить `MIN_RELEVANCE_SCORE` до 0.40 |

---

## Чек-лист готовности

- [ ] Docker и Docker Compose установлены
- [ ] Файл `.env` создан с `LLM_MODEL=llama3.1:8b`
- [ ] Все контейнеры запущены (`backend` и `celery` могут быть просто `Up` без healthcheck)
- [ ] Модель загружена (`model_available: true`)
- [ ] Модель инициализирована (первый запрос выполнен)
- [ ] Миграции БД накатаны
- [ ] Проверка готовности анализа пройдена
- [ ] Fallback-модель загружена (опционально)

---

## Контакты

При возникновении проблем проверьте:
1. Логи: `docker logs -f lexguard_celery`
2. Статус: `curl http://localhost:8000/api/v1/status`
3. Документацию: `docs/EDGE_CASES_AND_RISKS.md`
