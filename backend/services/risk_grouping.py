from __future__ import annotations

from collections import defaultdict

from models.schemas import AnalysisResponse


def group_analysis_risks(result: AnalysisResponse) -> dict:
    grouped: dict[str, dict] = {}
    buckets: defaultdict[str, list] = defaultdict(list)

    for risk in result.risks:
        if not risk.is_risky:
            continue
        category = risk.risk_category.value if risk.risk_category else "без категории"
        buckets[category].append(risk)

    for category, items in buckets.items():
        high = sum(1 for x in items if x.risk_level.value == "high")
        medium = sum(1 for x in items if x.risk_level.value == "medium")
        low = sum(1 for x in items if x.risk_level.value == "low")
        grouped[category] = {
            "category": category,
            "total": len(items),
            "high": high,
            "medium": medium,
            "low": low,
            "risks": items,
        }

    groups = sorted(
        grouped.values(),
        key=lambda g: (g["high"], g["medium"], g["low"], g["total"]),
        reverse=True,
    )

    return {
        "analysis_id": result.analysis_id,
        "filename": result.filename,
        "summary": result.summary,
        "executive_summary": result.executive_summary,
        "groups": groups,
    }

