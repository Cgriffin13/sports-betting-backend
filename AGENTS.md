# Repository Guidance for Codex

## Start here

Before changing this repository, read:

1. `docs/PROJECT_CONTEXT.md` for product purpose and boundaries.
2. `docs/ARCHITECTURE.md` for current and proposed system structure.
3. `docs/MODEL_LOGIC.md` before changing probability, EV, staking, settlement, or analytics logic.
4. `docs/ROADMAP.md` for sequencing and current priorities.
5. `docs/DECISIONS.md` for durable product and architecture decisions.

The code is the source of truth for what is implemented. The documentation is the source of truth for intended behavior and direction. If they conflict, report the conflict; do not silently describe planned behavior as implemented.

## Product constraints

- Treat this as an experimental paper-trading and portfolio-research platform, not a picks chatbot.
- Immediate league priority is NCAAF/College Football, then NFL, then NBA. MLB, NHL, and WNBA are secondary. Never confuse NCAAF with the prototype's existing NCAAB support.
- The product combines market pricing, sport-specific predictive models, structured sports data, traceable research signals, and portfolio risk. Market consensus is the baseline and benchmark, not necessarily the final long-term fair probability.
- Official bets require explicit human approval. Do not add autonomous real-money sportsbook execution unless the product direction is explicitly changed and recorded.
- Never use full Kelly staking. Historical stake ranges are context, not hard-coded rules.
- Do not call a market-derived consensus probability a proprietary predictive model.
- Return only qualified recommendations up to the requested Top N; never lower standards or manufacture bets to fill a quota.
- LLM-derived research must remain traceable and must not create undocumented probability adjustments.
- Do not let small samples directly drive large model-weight or staking changes.

## Engineering rules

- Preserve secrets in environment variables. Never commit, log, or return credentials or credential-bearing provider URLs.
- Keep provider-specific data behind adapters and normalize it before pricing or portfolio logic.
- Make financial and probability calculations deterministic, side-effect free, explicitly named, and covered by unit tests.
- Validate numeric inputs as finite and within their valid domains. Define rounding and money semantics explicitly.
- Preserve an auditable bet snapshot: event, market, line, price, probabilities, model/version, bankroll, approval, timestamps, closing data, result, and P&L.
- Scale position sizing from current portfolio equity under a versioned risk policy. Treat units as a bankroll-relative display abstraction, not a fixed dollar constant.
- Prefer database transactions, idempotency, and immutable ledger-style records over shared mutable state.
- Update the relevant documentation and `docs/DECISIONS.md` when a change alters architecture, financial semantics, model terminology, or product boundaries.
- Do not mix broad refactors with behavior changes unless the task requires both.

## Validation

Before completing a change:

- Inspect the diff and confirm no unrelated files or secrets were added.
- Run the narrowest relevant tests, then the full suite when one exists.
- Add deterministic tests for every new probability, EV, staking, settlement, bankroll, or analytics rule.
- Test failure cases and invariants, not only happy paths.
- For API changes, verify request validation, response contracts, authentication, idempotency, and sanitized provider failures.
- For persistence changes, verify migrations, transactions, concurrent updates, and rollback behavior.
- For documentation-only changes, check internal links, terminology, current-versus-planned labels, and consistency with the code.

The prototype currently has no test or lint configuration. Do not claim validation that the repository cannot perform; state what was checked and add appropriate tooling as part of the relevant roadmap phase.

