# LexGuard Roadmap: Priorities and Execution Plan

## Goal
Bring LexGuard to production-grade quality for diploma defense:
- stronger legal norms base,
- clearer and scalable risk output UX,
- stable architecture with measurable quality.

## Priorities

### P0: Immediate impact (in progress)
1. Improve risk output readability for large contracts.
2. Fix contract type normalization in RAG filtering.
3. Prepare norms payload for weighted risk calibration.

### P1: Core model quality
1. Expand `legal_norms.json` coverage and quality.
2. Add criticality tags and deception patterns to norms.
3. Introduce QA checks for norms consistency.

### P2: Advanced UX and explainability
1. Text highlighting mode (left: source, right: explanation).
2. Section-level navigation by risky fragments.
3. Rich export (JSON + human-readable report).

## Implementation Breakdown

### Stream A: Legal Norms Upgrade
1. Define canonical schema for one norm:
   - `contract_type`
   - `risk_category`
   - `topic`
   - `safe_norm`
   - `risky_pattern`
   - `criticality` (`low|medium|high|critical`)
   - `deception_patterns` (list of trap formulations)
2. Migrate existing norms to canonical schema.
3. Expand to at least 250 norms by priority contract types:
   - software development
   - outsourcing
   - nda
   - sla
4. Add validation script (schema + duplicates + empty fields).

### Stream B: Output Transformation
1. Add `Executive Summary` block for quick legal triage.
2. Add category grouping in UI and API semantics.
3. Preserve risk-level filters for detailed review.
4. Add highlighting mode (separate increment).

### Stream C: Reliability and Quality Gates
1. Add integration tests for new filters and summary generation.
2. Add stress tests on large contracts (40+ risks).
3. Add regression checks for RAG retrieval by contract type.

## Delivery Order
1. P0 Output readability + RAG contract type fix.
2. P1 Norms expansion and tagging.
3. P2 Highlighting and advanced explainability.

## Definition of Done (Diploma-ready)
- Large contracts remain readable in UI.
- Norm base has explicit criticality and trap patterns.
- RAG returns relevant norms for each supported contract type.
- Test suite covers edge cases and regressions.
- Architecture and product behavior are documented and reproducible.
