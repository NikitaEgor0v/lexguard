#!/usr/bin/env python3
"""
Validate backend/data/legal_norms.json against canonical LexGuard schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_CATEGORIES = {
    "финансовый",
    "правовой",
    "операционный",
    "репутационный",
    "интеллектуальный",
}

ALLOWED_CRITICALITY = {"low", "medium", "high", "critical"}
ALLOWED_CONTRACT_TYPES = {
    "software_development",
    "nda",
    "sla",
    "outsourcing",
    "услуги",
    "подряд",
    "поставка",
    "аренда",
    "трудовой",
    "лицензионный",
    "агентский",
    "все",
}

REQUIRED_FIELDS = (
    "id",
    "contract_type",
    "risk_category",
    "topic",
    "safe_norm",
    "risky_pattern",
    "criticality",
    "deception_patterns",
    "legal_basis",
)


def validate_item(item: dict, index: int, seen_ids: set[int], errors: list[str]) -> None:
    prefix = f"[#{index}]"
    for field in REQUIRED_FIELDS:
        if field not in item:
            errors.append(f"{prefix} missing field: {field}")

    raw_id = item.get("id")
    if not isinstance(raw_id, int):
        errors.append(f"{prefix} id must be int")
    elif raw_id in seen_ids:
        errors.append(f"{prefix} duplicate id: {raw_id}")
    else:
        seen_ids.add(raw_id)

    contract_type = str(item.get("contract_type", "")).strip().lower()
    if contract_type not in ALLOWED_CONTRACT_TYPES:
        errors.append(f"{prefix} invalid contract_type: {contract_type}")

    category = str(item.get("risk_category", "")).strip().lower()
    if category not in ALLOWED_CATEGORIES:
        errors.append(f"{prefix} invalid risk_category: {category}")

    criticality = str(item.get("criticality", "")).strip().lower()
    if criticality not in ALLOWED_CRITICALITY:
        errors.append(f"{prefix} invalid criticality: {criticality}")

    topic_value = str(item.get("topic", "")).strip()
    if len(topic_value) < 2:
        errors.append(f"{prefix} too short topic")

    safe_norm_value = str(item.get("safe_norm", "")).strip()
    if len(safe_norm_value) < 20:
        errors.append(f"{prefix} too short safe_norm")

    risky_pattern_value = str(item.get("risky_pattern", "")).strip()
    if len(risky_pattern_value) < 5:
        errors.append(f"{prefix} too short risky_pattern")

    patterns = item.get("deception_patterns")
    if not isinstance(patterns, list) or not patterns:
        errors.append(f"{prefix} deception_patterns must be non-empty list")
    else:
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, str) or len(pattern.strip()) < 5:
                errors.append(f"{prefix} invalid deception_patterns[{i}]")

    legal_basis = item.get("legal_basis")
    if not isinstance(legal_basis, list) or not legal_basis:
        errors.append(f"{prefix} legal_basis must be non-empty list")
    else:
        for i, basis in enumerate(legal_basis):
            if not isinstance(basis, str) or len(basis.strip()) < 5:
                errors.append(f"{prefix} invalid legal_basis[{i}]")


def main() -> int:
    norms_path = Path(__file__).resolve().parent.parent / "data" / "legal_norms.json"
    data = json.loads(norms_path.read_text(encoding="utf-8"))

    if not isinstance(data, list):
        print("ERROR: legal_norms.json must be a list")
        return 1

    errors: list[str] = []
    seen_ids: set[int] = set()
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            errors.append(f"[#{idx}] item must be object")
            continue
        validate_item(item, idx, seen_ids, errors)

    if errors:
        print(f"Validation failed ({len(errors)} errors):")
        for err in errors:
            print(f" - {err}")
        return 1

    print(f"OK: validated {len(data)} legal norms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
