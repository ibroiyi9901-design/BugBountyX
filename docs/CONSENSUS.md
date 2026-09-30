# BugBountyX Consensus Model

## One boundary, on purpose

BugBountyX has exactly one nondeterministic method: `triage_report(report_id)`.

Everything else — program creation, escrow funding, pause/resume/close, retiering, report intake, payout claims, disputes, arbitration, fee and ownership admin — is deterministic. That is not an implementation shortcut; it is the main safety property of the contract.

Deterministic intake means a report's existence, authorship, and claimed severity are the same on every node, so no leader can decide not to accept a hunter's work. Deterministic settlement means the transfer amount is not a model output. The only genuinely uncertain question — "is this report real, in scope, and how bad is it?" — is the only one that costs consensus.

## Why a comparative equivalence check rather than a validator LLM

Two validators can honestly read the same PoC and grade it differently. `gl.vm.run_nondet_unsafe` with a validator prompt would require a second, custom judgment about whether the leader's answer is acceptable, and that judgment is itself a model call with its own failure modes.

`gl.eq_principle.prompt_comparative` is a better fit for this shape of problem:

1. The leader runs the triage prompt and proposes a bounded verdict.
2. **Every validator independently re-runs the same prompt** against the same on-chain inputs. Validators are not asked "is the leader right?" — they answer the question themselves.
3. An `EqComparative` judge then accepts only verdicts that are materially equivalent.

Because validators re-derive rather than review, a leader cannot smuggle a verdict past them by phrasing a result persuasively. The judge only decides whether two independently derived verdicts agree.

## The leader task

The prompt is built entirely from state that was copied out of storage before the nondeterministic block — storage is invisible inside it:

```text
SCOPE:        program.scope
REPORT:       title / description / PoC / impact / claimed severity
EXISTING:     up to 20 "id | title | severity" lines for valid+paid reports
```

and demands a single JSON object and nothing else:

```json
{
  "decision": "valid | invalid | duplicate",
  "severity": "critical | high | medium | low | info",
  "duplicate_of": 0,
  "reason": "one line"
}
```

The raw model output is then forced through `_clean` and `_norm` before it is allowed to influence anything:

- `dict` passes through; non-strings become `{}`.
- ```` ```json ```` fences are stripped, then the first `{` … last `}` substring is extracted.
- Unparseable output becomes `{}`.
- Missing or unknown `decision` is inferred from key variants: `is_duplicate: true` → duplicate, `is_valid: false` or `in_scope: false` → invalid, `is_valid: true` → valid, otherwise invalid.
- `severity` is coerced to one of the five tiers, defaulting to `info`.
- `duplicate_of` is coerced to a non-negative `u256`, defaulting to `0`.
- `reason` is truncated to 280 characters.

Every one of those coercions fails *closed*: the fallback is the decision that pays nobody.

Finally the node derives the money itself:

```text
out["reward"] = _tier_payout((reward_critical, reward_high, reward_medium, reward_low),
                             out["severity"])
```

The model never sees or chooses an amount. It picks a tier, and the table decides the GEN.

## The equivalence principle

```text
The `decision` must be identical. If duplicate, `duplicate_of` must
match. `severity` may differ by at most one tier but same risk band,
and `reward` — the GEN the program pays for that severity per its
reward table — must be identical: verdicts that would pay different
amounts are not equivalent.
```

Read field by field:

| Field | Rule | Why |
|---|---|---|
| `decision` | exact | A `valid` and an `invalid` verdict are not the same outcome. No tolerance. |
| `duplicate_of` | exact, when duplicating | The cited id is a fact about state, not a judgement. Two different ids mean two different reports. |
| `severity` | within one tier, same band | Grading is genuinely fuzzy. `high` vs `medium` is a labelling disagreement, not a disagreement about the finding. |
| `reward` | exact | The transfer amount. Derived from severity and the table, so tier tolerance cannot move money. |
| `reason` | unconstrained | Explanatory prose. Requiring identical prose would reject substantively identical verdicts for cosmetic reasons. |

`reward` is the load-bearing row. Severity tolerance is granted *only* because the amount it implies is separately pinned, so a validator set can be fuzzy about the label and precise about the money.

## What settlement still checks

Consensus is necessary but not sufficient. After it returns, deterministic code verifies:

1. **Duplicate citation is real.** `duplicate_of` must be non-zero, exist, belong to the same program, be `valid` or `paid`, and not be the report itself. Otherwise the verdict is downgraded to `valid`.
2. **Reward matches stored tiers.** `self._reward_for(program_id, severity)` is recomputed from storage and compared to the consensus `reward`. A mismatch raises `"Payout not bound by consensus"` and the whole transaction reverts.
3. **Escrow can cover it.** `_pay` checks `escrow_bal >= amount` before touching the ledger. If it cannot, the report stays `valid` with its `payout` recorded, and `claim_payout` pays it later once the program is funded.

That last behaviour is deliberate: an underfunded escrow must not destroy an adjudicated finding. The report keeps its verdict and its amount, and settlement simply waits.

## Consensus failure behaviour

If validators reject the leader's verdict, the transaction does not finalize with it. The contract does not coerce a rejected or malformed verdict into a paid report, and it does not fall back to a "closest" verdict.

The report stays `pending` and `triage_report` can be called again by anyone. There is no griefing penalty for a failed triage, which is intentional — requiring a stake to attempt consensus would let a sponsor suppress triage by making it expensive.

## Prompt-injection boundary

Report text is hunter-controlled (`title`, `description`, `poc`, `impact`), and program scope is sponsor-controlled. Both are interpolated into the prompt, so both are injection surfaces.

Mitigations:

- Validators independently re-run the prompt rather than reviewing a leader's prose, so injected instructions in one node's context do not travel.
- The output is bounded: three enums, one integer, a 280-character reason.
- The model cannot choose an amount. A successful injection that flips a verdict can at worst mis-grade a report, and mis-grading is contestable.
- A sponsor that injects into its own scope is arguing against its own scope narrowing; a hunter that injects is attacking a verdict they can dispute.

Residual limitation: no prompt boundary proves that a model read the report correctly. A hunter who convinces the validator set that a nonsense report is `critical` still gets paid for `critical` — which is why the reward table, not the model, is the real economic control on the program.

## What consensus does not decide

- **How much GEN moves.** Derived from the reward table; re-derived and re-checked at settlement.
- **Whether a duplicate citation is real.** Verified against storage.
- **Who may triage, dispute, or arbitrate.** Deterministic address checks.
- **Whether the program is open, paused, or closed.** Deterministic lifecycle state.
- **Whether the fee is fair.** Owner-set, capped at 10%, deterministic.
