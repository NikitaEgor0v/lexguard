# Схема эталонных правовых норм

Файл `backend/data/legal_norms.json` хранит эталонные правовые нормы для RAG-поиска.

---

## Обязательные поля

| Поле | Тип | Описание |
|------|-----|---------|
| `id` | int, unique | Уникальный идентификатор |
| `contract_type` | string | Тип договора |
| `risk_category` | string | Категория риска |
| `topic` | string | Тема нормы |
| `safe_norm` | string | Безопасная формулировка (эталон) |
| `risky_pattern` | string | Опасная формулировка (паттерн риска) |
| `criticality` | string | Уровень критичности |
| `deception_patterns` | string[] | Паттерны уловок (непустой массив) |
| `legal_basis` | string[] | Правовые основания, например `ГК РФ ст. 309` |

Опциональное поле: `explanation` (string).

---

## Допустимые значения

### `contract_type`

| Значение | Описание |
|----------|---------|
| `software_development` | Разработка ПО |
| `nda` | Соглашение о неразглашении |
| `sla` | Service Level Agreement |
| `outsourcing` | Аутсорсинг |
| `услуги` | Оказание услуг |
| `подряд` | Подря�� |
| `поставка` | Поставка |
| `аренда` | Аренда |
| `трудовой` | Трудовой договор |
| `лицензионный` | Лицензионный договор |
| `агентский` | Агентский договор |
| `все` | Универсальная норма (применяется ко всем типам) |

### `risk_category`

- `финансовый`
- `правовой`
- `операционный`
- `репутационный`
- `интеллектуальный`

### `criticality`

- `low`
- `medium`
- `high`
- `critical`

---

## Как используется в RAG

1. При индексации в Qdrant эмбеддинг строится по `safe_norm + risky_pattern`
2. Payload содержит: safe_norm, risk_category, contract_type, criticality, deception_patterns, legal_basis, topic, risky_pattern
3. При поиске результат преобразуется в `RAGChunk` с полями `etalon` (safe_norm) и `risk` (risky_pattern)
4. В промпт передаётся в формате:
   ```
   ЭТАЛОН (безопасная формулировка): {safe_norm}
   РИСК (опасная формулировка): {risky_pattern}
   КАТЕГОРИЯ: {risk_category}
   ОСНОВАНИЕ: {legal_basis}
   ```

---

## Алиасы типов договоров

При RAG-поиске система учитывает алиасы (файл `rag.py`):

| Тип | Дополнительно ищет |
|-----|--------------------|
| услуги | software_development, outsourcing |
| подряд | software_development |
| поставка | outsourcing |
| нда | nda |
| агентский | outsourcing |
| лицензионный | software_development |

Универсальные типы (`все`, `all`, `any`, `любой`, `иной`) всегда включаются в результаты поиска.

---

## Валидация

Перед коммитом изменений в нормы:

```bash
python backend/scripts/validate_legal_norms.py
```

Генерация расширенного датасета:

```bash
python backend/scripts/generate_extended_legal_norms.py
```

Валидатор проверяет:
- Соответствие JSON-схеме
- Уникальность `id`
- Допустимые значения enum-полей
- Минимальное качество текста
