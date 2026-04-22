import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.risk_grouping import group_analysis_risks
from models.schemas import RiskLevel, RiskCategory

def test_risk_grouping_logic(sample_analysis_response):
    """Проверка корректности группировки рисков по категориям."""
    # Создаем 10 рисков с 4 уровнями и 5 категориями (циклически)
    # levels = [HIGH, MEDIUM, LOW, NONE]
    # cats = [FINANCIAL, LEGAL, OPERATIONAL, INTELLECTUAL, REPUTATIONAL]
    # is_risky = level != NONE
    result = sample_analysis_response(num_risks=10)
    
    grouped = group_analysis_risks(result)
    
    assert grouped["analysis_id"] == result.analysis_id
    assert "groups" in grouped
    
    groups = grouped["groups"]
    # 10 рисков: 
    # i=0: HIGH, FINANCIAL -> risky
    # i=1: MEDIUM, LEGAL -> risky
    # i=2: LOW, OPERATIONAL -> risky
    # i=3: NONE, INTELLECTUAL -> not risky
    # i=4: HIGH, REPUTATIONAL -> risky
    # i=5: MEDIUM, FINANCIAL -> risky
    # i=6: LOW, LEGAL -> risky
    # i=7: NONE, OPERATIONAL -> not risky
    # i=8: HIGH, INTELLECTUAL -> risky
    # i=9: MEDIUM, REPUTATIONAL -> risky
    
    # Итого рискованных: 8
    # Категории рискованных:
    # FINANCIAL: 2 (HIGH, MEDIUM)
    # LEGAL: 2 (MEDIUM, LOW)
    # OPERATIONAL: 1 (LOW)
    # INTELLECTUAL: 1 (HIGH)
    # REPUTATIONAL: 2 (HIGH, MEDIUM)
    
    assert len(groups) == 5
    
    # Проверяем конкретную категорию (например, FINANCIAL)
    fin_group = next(g for g in groups if g["category"] == RiskCategory.FINANCIAL.value)
    assert fin_group["total"] == 2
    assert fin_group["high"] == 1
    assert fin_group["medium"] == 1
    assert fin_group["low"] == 0
    assert len(fin_group["risks"]) == 2

def test_risk_grouping_sorting(sample_analysis_response):
    """Проверка сортировки групп по уровню опасности."""
    result = sample_analysis_response(num_risks=10)
    grouped = group_analysis_risks(result)
    groups = grouped["groups"]
    
    # Сортировка: high DESC, medium DESC, low DESC, total DESC
    for i in range(len(groups) - 1):
        g1 = groups[i]
        g2 = groups[i+1]
        
        # Проверяем лексикографический порядок
        score1 = (g1["high"], g1["medium"], g1["low"], g1["total"])
        score2 = (g2["high"], g2["medium"], g2["low"], g2["total"])
        assert score1 >= score2

def test_risk_grouping_no_risks(sample_analysis_response):
    """Проверка группировки при отсутствии рисков."""
    # Все уровни рисков - NONE
    result = sample_analysis_response(num_risks=5)
    for r in result.risks:
        r.is_risky = False
        r.risk_level = RiskLevel.NONE
        r.risk_category = None
    
    grouped = group_analysis_risks(result)
    assert len(grouped["groups"]) == 0
