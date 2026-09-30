# Proof directory

## Status: no live evidence captured yet

BugBountyX has not been deployed to a public GenLayer network, so this directory
is currently empty of receipts. Nothing here is reconstructed, simulated, or
hand-written — a proof file is only added once a real transaction hash and a
real `FINALIZED` receipt exist to back it.

The contract has been verified offline (`scripts/preflight.py`, 29 checks) and in
Direct Mode (`tests/direct/test_bugbountyx.py`). Direct Mode runs the leader
function only, so it is **not** consensus evidence. The first files to land here
must come from a real consensus run of `triage_report`.

## What belongs here

Sanitized extracts of observed GenLayer CLI receipts and state reads:

| File | Contents |
|---|---|
| `deployment-receipt.json` | Contract address, deploy transaction hash, finalization status |
| `program-receipt.json` | `create_program` return (`program_id`) and the reward table as stored |
| `funding-receipt.json` | `fund_program` transaction, value sent, resulting `escrow_bal` |
| `triage-receipt.json` | **The key artifact.** `triage_report` transaction hash, `MAJORITY_AGREE` / `FINALIZED`, and the returned decision dict |
| `report-state.json` | `get_report` after triage, showing `severity_ai`, `status`, and `payout` |
| `program-stats.json` | `get_program_stats` after triage, showing `total_paid` moved out of `escrow_bal` |
| `dispute-receipt.json` | `raise_dispute` return (`dispute_id`) and the frozen `disputed` status |
| `dispute-state.json` | `get_dispute` after `resolve_dispute`, showing the `bound_rewards` the arbitration paid from |

Files named `raw-*` contain raw public RPC responses. Files named `*-summary`
contain accurately labelled sanitized CLI summaries. If a file is a hand-written
summary rather than a raw response, it must be named accordingly.

## Naming convention

Use the network and a UTC timestamp so multiple deployments can coexist:

```text
<network>-<UTC timestamp>-<method>.json
```

for example `studionet-2026-09-30-14-22-07-triage_report.json`.

## Sanitization rules

Include:

- transaction hashes;
- contract address, program id, report id, dispute id;
- reward tiers, `escrow_bal`, `payout`, fee values;
- the returned decision dict and the triage reason string;
- `status_name` and `execution_result` from the receipt.

Omit:

- validator private keys and account credentials;
- API tokens, RPC URLs containing keys, and machine-local configuration;
- local file paths and account labels that identify a person.

## How to capture

```bash
export BUGBOUNTYX="0x..."

# deploy
genlayer deploy --contract contracts/BugBountyX.py

# deterministic setup
genlayer write "$BUGBOUNTYX" create_program --args "Vault Bounty" "scope text" 1000 500 100 50
genlayer write "$BUGBOUNTYX" fund_program   --args 1 --value 2000000000000000000
genlayer write "$BUGBOUNTYX" submit_report  --args 1 "title" "desc" "poc" "impact" high

# consensus: this receipt is the evidence that matters
genlayer write "$BUGBOUNTYX" triage_report  --args 1
genlayer receipt <triage_tx_hash> --status FINALIZED --retries 180 --interval 3000

# state reads proving the derived payout
genlayer call "$BUGBOUNTYX" get_report         --args 1
genlayer call "$BUGBOUNTYX" get_program_stats  --args 1

# optional: the dispute path and the reward table bound at raise time
genlayer write "$BUGBOUNTYX" raise_dispute --args 1 "severity is understated"
genlayer call  "$BUGBOUNTYX" get_dispute   --args 1
```

`scripts/smoke.sh --write` performs exactly this sequence and prints each
transaction hash, so it can be used as the capture driver. See
[`DEPLOYMENT.md`](../DEPLOYMENT.md) for the annotated command sheet.

## What the triage receipt must demonstrate

A reviewer should be able to confirm from `triage-receipt.json` plus
`report-state.json` that:

1. the transaction reached `status_name: 'FINALIZED'` with
   `execution_result: 'SUCCESS'` — acceptance alone is not finalization, and
   finalization alone is not successful execution;
2. consensus reported `MAJORITY_AGREE` rather than a leader-only result;
3. the recorded `payout` equals the reward table's amount for the recorded
   `severity_ai` — this is the consensus-bound derivation, and it should be
   checkable by hand;
4. `total_paid` in `program-stats.json` increased by the same amount while
   `escrow_bal` decreased by it plus the fee.

Point 3 is the one worth demonstrating explicitly. The contract reverts with
`"Payout not bound by consensus"` if the settled amount disagrees with the
consensus-derived amount, so a `SUCCESS` receipt on a `valid` report is itself
evidence that the amount was consensus-bound.
