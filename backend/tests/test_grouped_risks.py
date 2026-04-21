from services.risk_grouping import group_analysis_risks


def test_group_analysis_risks_groups_by_category(sample_analysis_response):
    analysis = sample_analysis_response(num_risks=6)
    grouped = group_analysis_risks(analysis)

    assert grouped["analysis_id"] == analysis.analysis_id
    assert "groups" in grouped
    assert len(grouped["groups"]) > 0

    totals = sum(group["total"] for group in grouped["groups"])
    assert totals == len(analysis.risks)
