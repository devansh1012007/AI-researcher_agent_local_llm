# Example Researcher Inherited Pack (`example_researcher_inherited`)

Demonstrates **Way 3** of adding a new researcher agent to GAR: scaffolding/inheriting from an existing engine (`extends: example_researcher`) via `research engine new example_researcher_inherited --extends example_researcher` so all parent branches (`EXAMPLE_ALPHA`, `EXAMPLE_BETA`, `EXAMPLE_JIBRISH`, `EXAMPLE_WIDGETS`), loop steps, and safety rules are inherited automatically while overriding `clarifier`, `extraction`, `tunables`, `schema.json`, and `skills/`.
