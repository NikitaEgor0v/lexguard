# Legal Norms Canonical Schema

`backend/data/legal_norms.json` stores reference legal norms for RAG retrieval.

## Required fields

Each norm object must contain:

- `id` (int, unique)
- `contract_type` (string)
- `risk_category` (string)
- `topic` (string)
- `safe_norm` (string)
- `risky_pattern` (string)
- `criticality` (`low|medium|high|critical`)
- `deception_patterns` (non-empty array of strings)
- `legal_basis` (non-empty array of legal references, e.g. `ГК РФ ст. 309`)

Optional legacy field:

- `explanation` (string)

## Allowed values

`contract_type`:
- `software_development`
- `nda`
- `sla`
- `outsourcing`
- `услуги`
- `подряд`
- `поставка`
- `аренда`
- `трудовой`
- `лицензионный`
- `агентский`
- `все`

`risk_category`:
- `финансовый`
- `правовой`
- `операционный`
- `репутационный`
- `интеллектуальный`

`criticality`:
- `low`
- `medium`
- `high`
- `critical`

## Validation

Run validator before committing any update to norms:

```bash
python backend/scripts/validate_legal_norms.py
```

Regenerate extended baseline dataset:

```bash
python backend/scripts/generate_extended_legal_norms.py
```

The script checks schema shape, uniqueness of `id`, allowed enums, and minimum text quality constraints.
