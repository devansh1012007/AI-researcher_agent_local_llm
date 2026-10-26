# Skill: Source Evaluation

## Objective
Decide which discovered sources deserve fetch/parse budget and how much weight their
evidence carries.

## Signals
- URL/domain class (deterministic first pass): tld, known platforms.
- Type: primary > structured secondary > journalism > community > unknown.
- Recency relative to the question's time horizon.
- Independence: syndication and republished press releases are NOT independent
  confirmations (content-hash dedup catches exact copies; near-duplicates flagged).
- Conflicts of interest: vendor claims about their own product need independent
  corroboration before raising claim confidence.

## Rules
- Tier is a prior, never proof. A tier-1 source can be wrong; contradictions still count.
- Weight evidence by tier x extraction confidence x independent corroboration.
- Rejected sources keep audit records with reasons.

## Failure conditions
- Over 70% duplicates in a cycle -> source diversity exhausted, converge.
