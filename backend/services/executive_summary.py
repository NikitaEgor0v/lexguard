from __future__ import annotations

from models.schemas import AnalysisSummary, RiskItem


def build_executive_summary(summary: AnalysisSummary, risks: list[RiskItem]) -> str:
    risky_items = [item for item in risks if item.is_risky]
    if not risky_items:
        return (
            "Договор выглядит низкорисковым: критичные формулировки не обнаружены. "
            "Рекомендуется финальная ручная верификация перед подписанием."
        )

    if summary.high_risk_count > 0 or summary.risk_score >= 0.6:
        risk_band = "высокорисковый"
    elif summary.risk_score <= 0.3:
        risk_band = "низкорисковый"
    else:
        risk_band = "среднерисковый"

    category_labels = {
        "финансовый": "Финансы",
        "правовой": "Право",
        "операционный": "Операции",
        "репутационный": "Репутация",
        "интеллектуальный": "Интеллектуальная собственность",
    }

    category_counts: dict[str, int] = {}
    for item in risky_items:
        key = item.risk_category.value if item.risk_category else "без категории"
        category_counts[key] = category_counts.get(key, 0) + 1

    top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:2]
    top_categories_text = ", ".join(
        f"{category_labels.get(key, key.title())} ({count})"
        for key, count in top_categories
    )

    top_critical = [item for item in risky_items if item.risk_level.value == "high"][:2]
    if top_critical:
        critical_text = "; ".join(
            f"п. {item.segment_id}: {item.risk_description or 'требует ручной проверки'}"
            for item in top_critical
        )
    else:
        critical_text = "критичных пунктов не обнаружено, приоритет на средних рисках"

    return (
        f"Договор классифицирован как {risk_band}: обнаружено {len(risky_items)} риск-сегментов "
        f"из {summary.total_segments}. "
        f"Ключевые зоны риска: {top_categories_text or 'требуют дополнительной ручной группировки'}. "
        f"Приоритетно проверить: {critical_text}."
    )

