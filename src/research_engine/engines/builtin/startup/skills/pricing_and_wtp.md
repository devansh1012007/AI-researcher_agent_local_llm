---
phase: extract
priority: 35
---
# Skill: Pricing & Willingness-to-Pay Extraction

## Objective
Extract verifiable competitor pricing tiers, billing units, and customer budget constraints without conflating company revenue or funding rounds with unit prices.

## Extraction rules
- Record exact `price_raw`, currency, billing unit (`per seat/month`, `per transaction`, `annual contract`), and tier name.
- Distinguish self-serve published list prices from enterprise custom quotes.
- Flag single-geography pricing when evaluating a different regional market.
