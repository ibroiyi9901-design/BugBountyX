# Examples

## What goes in this directory

Terminal and Studio captures of real runs against a deployed BugBountyX
contract. Screenshots follow the same timestamped convention as the rest of the
repository, and each one should be traceable to a transaction hash that also
appears in [`../proof`](../proof).

```text
YYYY-MM-DD-HH-MM-SS.png
```

for example `2026-09-30-14-22-07.png` for the `triage_report` transaction whose
receipt is `../proof/studionet-2026-09-30-14-22-07-triage_report.json`.

No captures are committed yet, because no live run has been recorded. This file
is the walkthrough to capture, not a transcript of a run that happened.

---

## Walkthrough: from an empty contract to a consensus-bound payout

Each step below is one CLI call, the state it produces, and — for the consensus
step — the prompt the leader and every validator independently receive.

Set up first:

```bash
export BUGBOUNTYX="0x..."
```

### 1. Sponsor opens a program

```bash
genlayer write "$BUGBOUNTYX" create_program --args \
  "Vault Bounty" \
  "Vault and staking contracts. In scope: withdraw, deposit, share accounting, reentrancy. Out of scope: off-chain infra, third-party oracle failure." \
  1000 500 100 50
```

The reward table must descend `critical >= high >= medium >= low`, or the call
reverts. `info` has no reward and pays `0`.

Deterministic. No LLM.

### 2. Sponsor escrows GEN

```bash
genlayer write "$BUGBOUNTYX" fund_program --args 1 --value 2000000000000000000
```

Two GEN moves into escrow. This is the total the program is willing to lose;
when it runs out, valid reports stop auto-paying but keep their verdict.

Deterministic.

### 3. Hunter submits a report

```bash
genlayer write "$BUGBOUNTYX" submit_report --args 1 \
  "Reentrancy in Vault.withdraw drains pooled funds" \
  "Vault.withdraw sends GEN to msg.sender before decrementing shares, so the recipient callback reenters with shares already counted as burned." \
  "1. deposit 1 GEN 2. call withdraw(1) 3. fallback reenters withdraw(1) before shares decrement 4. repeat until drained" \
  "Full loss of pooled vault funds in one transaction." \
  high
```

Report is now `pending`. `claimed` is stored as `high` and will never be
overwritten — the `claimed` / `severity_ai` pair is the audit trail of whether
consensus agreed with the hunter.

Deterministic.

### 4. Anyone triggers triage — the only consensus method

```bash
genlayer write "$BUGBOUNTYX" triage_report --args 1
genlayer receipt <tx_hash> --status FINALIZED --retries 180 --interval 3000
```

This is the step worth capturing. The receipt must show `MAJORITY_AGREE` and
`FINALIZED` with `execution_result: 'SUCCESS'`.

#### The prompt

Identical inputs on the leader and on every validator. Built entirely from state
copied out of storage before the nondeterministic block:

```text
You are a senior security researcher triaging a bug bounty.
SCOPE:
Vault and staking contracts. In scope: withdraw, deposit, share accounting,
reentrancy. Out of scope: off-chain infra, third-party oracle failure.
REPORT:
Title: Reentrancy in Vault.withdraw drains pooled funds
Desc: Vault.withdraw sends GEN to msg.sender before decrementing shares, so the
recipient callback reenters with shares already counted as burned.
PoC: 1. deposit 1 GEN 2. call withdraw(1) 3. fallback reenters withdraw(1)
before shares decrement 4. repeat until drained
Impact: Full loss of pooled vault funds in one transaction.
Claimed: high
EXISTING VALID (id|title|sev):
None
Decide scope/validity/dupe-id(0 if none)/severity.
ONLY JSON: {"decision":"valid|invalid|duplicate","severity":"critical|high|medium|low|info","duplicate_of":0,"reason":"one line"}
```

Note what is *not* in the prompt: the reward amounts. The model picks a tier; the
reward table decides the GEN.

#### The equivalence principle

```text
The `decision` must be identical. If duplicate, `duplicate_of` must
match. `severity` may differ by at most one tier but same risk band,
and `reward` — the GEN the program pays for that severity per its
reward table — must be identical: verdicts that would pay different
amounts are not equivalent.
```

#### What each node returns

A normalized verdict plus a reward it derived itself:

```json
{
  "decision": "valid",
  "severity": "high",
  "duplicate_of": 0,
  "reason": "state updated after external call; shares double-counted",
  "reward": 500
}
```

A leader saying `high` and a validator saying `medium` is an acceptable
disagreement — but only because `reward` is derived from the table, not chosen
by the model. If those two verdicts implied different GEN, consensus would fail.

If validators reject the verdict outright, the transaction does not finalize and
the report stays `pending`. There is no penalty for a failed triage, so nobody
can make triage too expensive to attempt.

#### Settlement

Deterministic, after consensus:

1. `duplicate_of` is checked against storage — here `0`, so nothing to verify.
2. `_reward_for(pid, "high")` is recomputed from the stored tiers and must equal
   the consensus `reward` of `500`. A mismatch reverts with
   `"Payout not bound by consensus"`.
3. `_pay` checks `escrow_bal >= 500`, debits the ledger, sends `490` to the
   hunter and `10` to the owner (2% default fee).
4. Status becomes `paid`.

#### The return value

```json
{ "report_id": 1, "decision": "paid", "severity": "high", "payout": 500 }
```

### 5. Read back the result

```bash
genlayer call "$BUGBOUNTYX" get_report        --args 1
genlayer call "$BUGBOUNTYX" get_program_stats --args 1
```

```json
{
  "id": 1, "program_id": 1, "hunter": "0x...",
  "title": "Reentrancy in Vault.withdraw drains pooled funds",
  "claimed": "high", "severity_ai": "high",
  "status": "paid", "duplicate_of": 0, "payout": 500,
  "reason": "state updated after external call; shares double-counted"
}
```

`payout` is `500`, the table's `high` tier — not the `1000` a model might have
been talked into, and not the hunter's claimed amount by coincidence. It is the
table's answer to the tier consensus agreed on.

### 6. Dispute path, if a party disagrees

```bash
genlayer write "$BUGBOUNTYX" raise_dispute     --args 1 "severity is understated"
genlayer write "$BUGBOUNTYX" requeue_disputed  --args 1     # sponsor or owner
genlayer write "$BUGBOUNTYX" resolve_dispute   --args 1 valid high   # owner only

genlayer call  "$BUGBOUNTYX" get_dispute       --args 1
```

`raise_dispute` freezes the report so no payout path can run, and snapshots the reward table into the dispute. `resolve_dispute` pays that snapshot, so a sponsor cannot retier between the two calls to change what the arbitration is worth:

```json
{
  "id": 1, "report_id": 1, "raised_by": "0x...",
  "reason": "severity is understated",
  "resolved": true, "outcome": "valid",
  "bound_rewards": { "critical": 1000, "high": 500, "medium": 100, "low": 50, "info": 0 }
}
```

`requeue_disputed` is the alternative: it returns the report to `pending` for a fresh consensus round. It does not carry the bound table forward, so the next `triage_report` reads the live one.

---

## Variants worth capturing

Once the happy path is recorded, these are the cases a reviewer will ask about:

| Variant | How to produce it | What it shows |
|---|---|---|
| Underfunded escrow | Triage without calling `fund_program` | Report becomes `valid` with `payout` set, not `paid`; verdict survives, transfer defers |
| Hallucinated duplicate | Report on a program with no prior valid reports | `duplicate_of` cannot be verified, so the verdict downgrades to `valid` |
| Real duplicate | Two reports on the same flaw | Second is `duplicate`, `duplicate_of` points at the first, no payout |
| Info-severity finding | A report graded `info` | `valid` with `payout: 0`; `claim_payout` correctly reverts |
| Consensus disagreement | Any report the validator set splits on | Transaction does not finalize; report stays `pending` |
| Dispute and requeue | Steps 6 above | Verdict is contestable without an owner override |
| Sponsor zeroes the table mid-dispute | `raise_dispute`, then `update_rewards 0 0 0 0`, then `resolve_dispute valid high` | Arbitration still pays 500 from `bound_rewards`; the sponsor cannot reprice a live contest |
