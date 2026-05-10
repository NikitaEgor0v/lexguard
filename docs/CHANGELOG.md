# Changelog

Журнал значимых изменений в проекте LexGuard.

---

## [2026-05-09] RAG: Исправлен safe_redaction и RAG-контаминация

**Проблема:** `safe_redaction` всегда был `null`; RAG притягивал нерелевантные фрагменты для нейтральных сегментов.

**Решение:**
- safe_redaction: заменена проверка пересечения на `SequenceMatcher` (порог 0.85), проверка на `DANGEROUS_PHRASES`
- Разрешён safe_redaction для HIGH и MEDIUM рисков
- RAG: порог `MIN_RELEVANCE_SCORE_DEFAULT` повышен до 0.80
- Эмбеддинг при индексации: `safe_norm + risky_pattern`
- `is_neutral_segment`: исправлена регулярка для цены, добавлен `NEUTRAL_SEGMENT_PATTERNS`
- `_classify_contract_type`: превью увеличено до 1500 символов, чтение середины документа

**Файлы:** `analyzer.py`, `rag.py`, `model_registry.py`

---

## [2026-05-09] Chat: Расширены возможности AI-ассистента

**Проблема:** AI-ассистент отвечал слишком ограниченно. При запросе "сгенерируй правильный пункт" давал общие рекомендации вместо текста.

**Решение:**
- Переработан промпт в `ChatContextBuilder`: генерация текста, предложение альтернатив, опора на ГК РФ
- Нумерация рисков: "Риск №1", "Риск №2" (по порядку, а не по segment_id)
- В промпт добавлена инструкция о интерпретации номеров рисков

**Файлы:** `chat_context_builder.py`

---

## [2026-05-09] UX: Улучшения интерфейса

- Кнопка "Анализировать" показывается при загрузке нового файла (`upload.js`)
- Typing indicator с Page Visibility API — перезапуск анимации при возврате на вкладку
- `pendingSessions` — сохранение состояния ожидания между чатами
- Исправлен дубль сообщения пользователя при восстановлении сессии

**Файлы:** `upload.js`, `chat.js`, `index.html`, `components.css`, `app.js`

---

## [2026-05-09] Docs: Синхронизация RUNBOOK с runtime

- Исправлен ожидаемый ответ `GET /health`
- Уточнён статус backend в `docker compose ps` (Up, без healthy)
- Пояснение: миграции применяются автоматически в `start.sh`

---

## [2026-05-08] P0/P1/P2: Безопасность, логика, целостность

### P0: Безопасность
- **IDOR Protection**: `_verify_analysis_owner()`, `_verify_session_owner()` для всех эндпоинтов
- **404** для несуществующих анализов (вместо ложного `processing`)
- **Heartbeat failure detection**: stale heartbeat → `failed`

### P1: Логика анализа
- **Инкрементальное batch-сохранение** по `ANALYSIS_BATCH_SIZE` (20)
- **User documents в RAG**: `UserRAGChunk`, объединённый поиск
- **Детерминированный merge**: system chunks (приоритет) → user chunks

### P2: Схема БД (миграция 007)
- CHECK constraints: status, risk_level, role
- UNIQUE: (analysis_id, segment_id)

**Файлы:** `routes.py`, `chat_routes.py`, `analyzer.py`, `rag.py`, миграция 007, тесты

---

## [2026-05-08] Production: Адаптивная конфигурация моделей

- `model_registry.py`: ModelConfig с адаптивными лимитами для каждой модели
- Runtime: `MAX_SEGMENT_CHARS`, `MAX_RAG_CONTEXT_CHARS`, `MAX_RAG_NORMS` из ModelConfig
- Унификация `OLLAMA_URL` (единый источник из env)
- Таймауты: `LLM_REQUEST_TIMEOUT=300`, `LLM_HEARTBEAT_TIMEOUT=600` (configurable)
- `docker-compose.yml`: все переменные пробрасываются через env
- `.env.example`: полностью переработан

---

## [2026-05-08] LLM: Критическое правило сравнения ЭТАЛОН vs РИСК

**Проблема:** Precision 19% — модель помечала безопасные формулировки как рискованные, реагируя на тему, а не на смысл.

**Решение:**
- В промпт добавлено правило: текст соответствует ЭТАЛОНУ → `is_risky: false`; соответствует РИСКУ → `is_risky: true`
- Примеры правильной классификации прямо в промпте
- Категории нейтральных сегментов (сумма, реквизиты, подписи, допсоглашения и др.)
- Дедупликация RAG chunks по SHA256 хешу
- Парсинг и валидация safe_redaction

---

## [2026-05-08] Infra: Nginx proxy recovery

- Docker DNS resolver (`127.0.0.11`) для пере-разрешения backend после рестарта
- `set $backend_upstream http://backend:8000` — переменная upstream вместо статического

---

## [2026-05-08] Fix: Heartbeat и ложный "Analysis interrupted"

- Возвращено регулярное обновление heartbeat: при старте, перед/после каждого сегмента, в `_call_llm()`
- Helper `_update_heartbeat()` для единообразного обновления Redis-ключа

---

## [2026-05-07] RAG: Anti-contamination и релевантность

- `SCORE_THRESHOLD` повышен для снижения false positives
- Добавлено правило анти-контаминации в промпт
- Расширен список рисков: подсудность, претензионный порядок
- `_validate_risk_relevance()`, `SAFE_PATTERNS`, `DANGEROUS_PHRASES`
- Позднее откачено (слишком жёстко для 2B модели)
