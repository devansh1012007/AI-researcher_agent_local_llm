# Evidence Grounding

Two independent gates; both must pass (INV-005).

1. **Quote verification** (`pipeline.evidence.verify_quote`): normalized/fuzzy
   containment of quote in chunk text. Proves EXISTENCE.
2. **Claim-support verification** (`pipeline/claim_support.py`): deterministic,
   fail-closed semantics over claim vs quote:
   CONTRADICTS / UNRELATED -> REJECTED (kept for audit)
   NEUTRAL -> UNVERIFIED
   WEAKLY/PARTIALLY/STRONGLY/ENTAILS -> EXTRACTED with support fields stored.

Detected failure classes: negation flip, contrast-clause stripping
("...although margins declined" cannot support "margins improved"),
figure mismatch, invented numbers, dropped hedges ("may"), quantifier
tightening ("up to X" -> "X"), correlation->causation upgrades,
unrelated vocabulary.

Downstream weighting multiplies tier-weight by support factor
(SUPPORT_FACTOR); only ENTAILS/STRONGLY/PARTIALLY count toward grounded
synthesis, and independence-aware aggregation caps swarm boosts (INV-007).

Legacy rows predating the checker carry support_verdict="" (factor 0.7).
