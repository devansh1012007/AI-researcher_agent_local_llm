# Canonical Entity Identity (INV-003)

Natural keys (domain-derived, not UUIDs):

| Entity | Natural key | Normalization |
|---|---|---|
| Market | market_slug | slugify(question/market name) |
| SizeEstimate | evidence_id | one attributed figure per evidence |
| Persona / JTBD | segment_id | segment vocabulary |
| Alternative | name | norm_name (case/punct/legal-suffix strip) |
| Competitor | name_lower column | norm_name |
| PricingPlan | vendor + price_raw + billing_period | case-insensitive vendor |
| DistributionChannel | name | case-insensitive |
| TechShift | description fingerprint (analyzer-side) | token hash |

Resolution: `find_by_natural_key` (physical col if indexed else JSON path,
case-insensitive) -> merge incoming INTO existing (lists union, provenance
preserved, original id kept) -> save. Fresh ids minted only for new entities.
DB-level UNIQUE expression indexes backstop races; on legacy DBs still
carrying duplicates the index creation is skipped+recorded until
`repair_project` dedupes and completes them.
