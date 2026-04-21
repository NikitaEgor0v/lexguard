# LexGuard Defense Demo Script

## Goal of the demo
Show that LexGuard:
- detects high-risk legal clauses in Russian contracts,
- explains findings with legal basis,
- remains usable on large documents thanks to grouped output and highlighting mode.

## Demo timing (7-9 minutes)

1. Intro (40-60 sec)
2. System launch and readiness (60 sec)
3. Contract analysis run (2-3 min)
4. Reading and triage of results (2 min)
5. Highlighting walkthrough and grouped API (1-2 min)
6. Final value statement (40 sec)

## Preparation checklist

1. Start stack:
```bash
docker compose up -d
```
2. Verify readiness:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/status
```
3. Make sure model and RAG are ready in UI status badge.
4. Prepare one test contract with mixed risks (financial, legal, IP, operational).

## Demo flow (speaker notes)

## 1) Intro
"LexGuard is a local AI legal analyzer for Russian contracts.  
It combines LLM + RAG with an extended legal norms base and does not send contract text to external cloud APIs."

## 2) Show architecture quickly
"Frontend sends document to FastAPI, processing runs in background via Celery, risks are persisted, and RAG retrieves legal templates with criticality, trap patterns, and legal basis."

## 3) Upload and run analysis
1. Upload PDF/DOCX in UI.
2. Start analysis.
3. While progress is running, explain the pipeline:
   - parsing and segmentation,
   - contract type detection,
   - RAG retrieval of legal norms,
   - risk classification.

## 4) Explain result quality
1. Open `Executive Summary`.
2. Show risk score and high/medium/low counts.
3. Open category tabs (Finance, Legal, Operations, IP, Reputation).
4. Open one high-risk card and point to:
   - risk description,
   - recommendation,
   - legal basis in RAG context.

## 5) Show highlighting mode
1. Click `Режим разметки`.
2. On left panel pick highlighted segment.
3. On right panel show explanation and jump to risk card.
4. Explain that this mode reduces review time on long contracts.

## 6) Show grouped API (optional but strong technical proof)
```bash
curl -s http://localhost:3000/api/v1/analyze/<ANALYSIS_ID>/grouped \
  -H "Cookie: access_token=<TOKEN>"
```
Comment:
"The backend can return grouped risk structure for integrations (BI dashboards, legal workflow tools, internal portals)."

## 7) Final statement
"LexGuard is production-oriented for internal legal review: local deployment, auditable risk logic, explainable findings, and scalable UX for large contracts."

## Q&A anchors (short answers)

1. Why local models?
- Confidentiality of contracts and predictable operating cost.

2. How do you reduce hallucinations?
- RAG context, strict JSON schema, and fallback logic.

3. Why this is better than plain LLM chat?
- Structured scoring, risk grouping, legal-basis context, and repeatable workflow.

4. How is legal base maintained?
- Canonical schema + validator + generator + incremental expert review.
