# BugBountyX Integration Guide

## Consumer pattern: escrow-gated release

A sponsor integrating a bounty program should not pay hunters directly. Open a program, fund it, and let consensus decide the amount:

```text
create_program(name, scope, reward_critical, reward_high, reward_medium, reward_low)
fund_program(pid)          # payable, repeatable
submit_report(pid, title, description, poc, impact, severity)  # hunter
triage_report(rid)         # anyone; pays automatically
```

The reward table is the economic control. The model only chooses a tier from those five, and the table decides the GEN. A sponsor who wants to cap total exposure funds exactly what they are willing to lose; when escrow runs dry, valid reports stop being `paid` and become claimable `valid` instead of being discarded.

## Consumer pattern: monitor the pending queue

Triage is permissionless, so someone has to notice pending reports. `get_pending_queue(limit)` returns a JSON array of pending report ids, and is the intended trigger:

```bash
genlayer call "$BUGBOUNTYX" get_pending_queue --args 10
```

A keeper, cron job, or sponsor bot can poll this and call `triage_report` on each id. Because triage is not required to be the submitter, the hunter cannot be forced to pay for their own adjudication.

Note that the pending queue is a status scan, not an event log. A report that is triaged between your read and your `triage_report` call reverts with `"Already triaged"`, which is expected and harmless.

## Consumer pattern: read program health

`get_program_stats(pid)` returns the aggregate a dashboard or a sponsor's alerting needs:

```json
{
  "program_id": 1,
  "total": 12,
  "valid": 5,
  "invalid": 4,
  "duplicates": 2,
  "pending": 1,
  "total_paid": 2500,
  "escrow_bal": 7500
}
```

`escrow_bal` against `total_paid` is the runway calculation. `valid` counts both `valid` and `paid`, so it includes findings that are adjudicated but not yet claimed — the amount a sponsor still owes lives in those reports' `payout` fields, not in the stats aggregate.

`get_program(pid)` is the single-record view, including the full reward table, status, and report count.

## Consumer pattern: reconcile a single report

`get_report(rid)` is the authoritative per-report record:

```json
{
  "id": 1,
  "program_id": 1,
  "hunter": "0x...",
  "title": "Reentrancy in withdraw",
  "description": "...",
  "poc": "...",
  "impact": "...",
  "claimed": "high",
  "severity_ai": "high",
  "status": "paid",
  "duplicate_of": 0,
  "payout": 500,
  "reason": "reproducible state change before interaction"
}
```

`claimed` and `severity_ai` are both retained and never overwritten. The pair is the audit trail: it shows whether consensus agreed with the hunter's claim, downgraded it, or graded it higher.

`status` values a consumer must handle:

| Status | Meaning | Hunter's next step |
|---|---|---|
| `pending` | Not yet adjudicated | Wait, or call `triage_report` |
| `valid` | Valid finding, payout recorded | `claim_payout` (needs escrow) |
| `paid` | Escrow released | Nothing |
| `invalid` | Consensus found no actionable finding | `raise_dispute` |
| `duplicate` | Consensus cited an earlier valid finding | `raise_dispute` |
| `disputed` | Frozen pending arbitration | Owner must `resolve_dispute` |

`payout` is the adjudicated amount and is **not** recomputed from the current reward table. A sponsor who retiers rewards after adjudication does not retroactively change what an already-decided report is owed. That is what makes `payout` safe to treat as a liability.

## Consumer pattern: audit an arbitration

`get_dispute(did)` is the arbitration trail:

```json
{
  "id": 1,
  "report_id": 1,
  "raised_by": "0x...",
  "reason": "severity is understated",
  "resolved": true,
  "outcome": "valid",
  "bound_rewards": { "critical": 1000, "high": 500, "medium": 100, "low": 50, "info": 0 }
}
```

`bound_rewards` is the table in force when the dispute was raised, and it is the table `resolve_dispute` paid from. A monitoring integration can therefore assert that an arbitration honoured its bound stakes rather than trusting that it did.

`resolved` stays `false` for a dispute that was requeued rather than arbitrated — `requeue_disputed` returns the report to `pending` and does not close the dispute record. That is intended: the dispute was never arbitrated, and leaving it open is the honest record.

## Consumer pattern: escrow exhaustion

When escrow is short, `_pay` returns `False` and `triage_report` records the report as `valid` with `payout` set rather than `paid`. The verdict survives; only the transfer is deferred.

The intended recovery is to fund the program again and let hunters call `claim_payout`. A sponsor who instead calls `close_program` refunds the remaining escrow to themselves and leaves those reports unclaimable — `claim_payout` will then revert with `"Escrow underfunded"`. See the residual limitation in [`THREAT_MODEL.md`](./THREAT_MODEL.md).

## Composition with disputes

Arbitration is the escape hatch for every verdict a party disagrees with, including ones consensus got wrong:

```text
raise_dispute(rid, reason)      # hunter or sponsor only; report -> disputed
resolve_dispute(did, outcome, new_severity)   # owner only
requeue_disputed(rid)           # owner or sponsor; back to pending for re-triage
```

`resolve_dispute` with `outcome = "valid"` pays the tier from the reward table **bound when the dispute was raised**, not the program's current table. Retiering in between does not change the arbitration, and `get_dispute(did)` returns the `bound_rewards` actually used, so an integrator can verify what an arbitration was worth.

`requeue_disputed` is the cheaper and often fairer path: it returns the report to `pending` so a fresh consensus round can grade it, rather than one owner key overriding a validator set. The trade-off is that a requeued report loses its bound table — the next triage reads the live one. If the sponsor retiers between the requeue and the re-triage, the fresh consensus is bound to the *new* table. A sponsor can therefore lower tiers to zero, requeue, and have the re-triage bind a zero payout.

Treat `requeue_disputed` as a signal to re-check `get_program` before the report is re-triaged, and prefer `resolve_dispute` when the intent is to preserve the original stakes.

A dispute freezes the report, so no payout path can run while arbitration is open.

## Owner capabilities and their limits

The owner is the fee recipient and the sole arbitrator. It can:

- set the fee, up to 10% of every payout (`set_fee`);
- resolve any dispute with any of the three outcomes and any severity tier;
- return a disputed report to `pending`;
- hand over the role (`transfer_ownership`).

It cannot:

- redirect escrow. Each program's balance can only be refunded to that program's own sponsor, by that program's own sponsor, through `close_program`;
- mint a payout. Amounts come from the reward table;
- triage. `triage_report` has no owner path;
- skip consensus to mark a report valid. Only `resolve_dispute` can, and it is recorded as an arbitration with an explicit outcome.

The fee is the only value the owner can extract directly, and it is capped at 10% per payout.

## Sponsor capabilities and their limits

A sponsor controls its own program: pause, resume, close, and retier. It cannot:

- reject or delete a report;
- block triage — anyone can call it;
- lower the reward of an already-adjudicated report;
- change another program's table.

## Reading from the CLI

```bash
export BUGBOUNTYX="0x..."

# program health and the pending queue
genlayer call "$BUGBOUNTYX" get_program        --args 1
genlayer call "$BUGBOUNTYX" get_program_stats  --args 1
genlayer call "$BUGBOUNTYX" get_pending_queue  --args 10

# one report, a page of a program's reports (JSON-array strings), and a dispute
genlayer call "$BUGBOUNTYX" get_report          --args 1
genlayer call "$BUGBOUNTYX" get_program_reports --args 1 0 20
genlayer call "$BUGBOUNTYX" get_dispute         --args 1
```

`get_program_reports(pid, offset, limit)` and `get_pending_queue(limit)` return JSON-encoded arrays as plain strings, not typed lists. Parse them with `json.loads`; the ABI is primitive-only by design. See [`ARCHITECTURE.md`](./ARCHITECTURE.md#abi-discipline).

## Recommended integration invariant

For anything that reacts to a verdict, pin all three:

1. the BugBountyX contract address;
2. the program id;
3. the reward table as it stood at triage time.

Do not treat the severity label alone as the payable amount. The payable amount is `payout` on the report, which is the reward-table derivation that consensus agreed on and settlement re-checked.

## Full command sheet

See [`DEPLOYMENT.md`](../DEPLOYMENT.md) for the deploy, fund, submit, triage, and dispute sequence, and `scripts/smoke.sh` for the automated version of the same walkthrough.
