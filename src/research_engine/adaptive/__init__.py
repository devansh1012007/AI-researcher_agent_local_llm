"""Phase 6 — process intelligence.

The platform learns which research strategies work best for different
research problems through MEASUREMENT and VERSIONED POLICY, never through
self-modification. Learning produces proposals; only explicit human
activation deploys them (spec §2/§63).

Layering (§61 — lower layers cannot override higher):
  hard invariants > security > research-quality policy > resource policy
  > adaptive optimization. Every learned adjustment here is bounded by
  clamps defined in this package.
"""
