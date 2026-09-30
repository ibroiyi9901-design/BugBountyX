# BugBountyX Deployment

## Current repository status

| Item | State |
|---|---|
| Contract | `contracts/BugBountyX.py`, 502 lines, runner pinned in the header comment |
| Offline preflight | `scripts/preflight.py` — 32/32 checks pass |
| Direct Mode tests | `tests/direct/test_bugbountyx.py` — leader-only, mocked LLM |
| LLM-resilience tests | `tests/test_normalizer.py` — no node required |
| Live deployment | **none yet** — no receipt exists in `proof/` |
| Public testnet address | **none yet** |

Direct Mode runs the leader function only. It is not consensus evidence. The
first item that should be added to `proof/` is a real `triage_report` receipt
showing `MAJORITY_AGREE` and `FINALIZED`.

## Requirements

- GenLayer CLI (`npm install -g genlayer`) for deploy and CLI calls
- `genvm-lint` for static checks (`pip install genvm-linter`)
- `genlayer-test` for Direct Mode and integration tests
- An unlocked, funded account on the target network

## Install CLI

```bash
npm install -g genlayer
genlayer --version
```

## Select a network

```bash
genlayer network set studionet          # hosted, gasless, rate-limited
genlayer network set testnet-bradbury   # real network, funded accounts needed
genlayer network set localnet           # full GenVM via Docker
```

Studio enforces per-IP limits of 60 req/min, 1000 req/hr, 10000 req/day. For a
long smoke sequence, prefer localnet or a testnet. A `-32028` error means the
pending queue is full (32 in-flight per sender) — wait for receipts rather than
firing writes in parallel.

## Lint before deploying

```bash
GENVM_VERSION=v0.3.0-rc7 genvm-lint check contracts/BugBountyX.py
```

Expect `lint ok` and `validation ok`. The runner version in the `# { "Depends":
... }` header must match the network you deploy to.

## Offline preflight

No network and no GenVM runtime required:

```bash
python3 scripts/preflight.py
```

This compiles the contract, checks imports, the single-consensus-boundary
invariant, the fail-closed settlement guards, the field truncation caps, and
exercises the pure normalization helpers against adversarial LLM output.

## Deploy

```bash
genlayer deploy --contract contracts/BugBountyX.py
genlayer schema "$BUGBOUNTYX"        # confirm the ABI loaded
```

Record the address and the deploy transaction hash. They go in
`proof/deployment-receipt.json`.

## Runtime smoke sequence

Every write below is a real transaction. The deterministic steps finalize
quickly; `triage_report` runs full consensus and needs a longer poll.

### Setup

```bash
export BUGBOUNTYX="0x..."
```

```bash
# 1. open a program. Rewards must descend critical >= high >= medium >= low.
genlayer write "$BUGBOUNTYX" create_program --args \
  "Vault Bounty" \
  "Vault and staking contracts. In scope: withdraw, deposit, share accounting, reentrancy. Out of scope: off-chain infra, third-party oracle failure." \
  1000 500 100 50
# -> returns program_id (1 on a fresh contract)

# 2. escrow 2 GEN
genlayer write "$BUGBOUNTYX" fund_program --args 1 --value 2000000000000000000
```

### Report intake

```bash
# 3. submit. Length minimums and a valid tier are enforced before storage.
genlayer write "$BUGBOUNTYX" submit_report --args 1 \
  "Reentrancy in Vault.withdraw drains pooled funds" \
  "Vault.withdraw sends GEN to msg.sender before decrementing shares, so the recipient callback reenters with shares already counted as burned." \
  "1. deposit 1 GEN 2. call withdraw(1) 3. fallback reenters withdraw(1) before shares decrement 4. repeat until drained" \
  "Full loss of pooled vault funds in one transaction." \
  high
# -> returns report_id (1 on a fresh contract)
```

### Consensus

```bash
# 4. the only nondeterministic method
genlayer write "$BUGBOUNTYX" triage_report --args 1
# capture the transaction hash, then wait for consensus
genlayer receipt <triage_tx_hash> --status FINALIZED --retries 180 --interval 3000
```

Confirm all three of these in the receipt:

- `status_name: 'FINALIZED'`
- `execution_result: 'SUCCESS'`
- consensus reported `MAJORITY_AGREE`, not a leader-only result

If validators reject the verdict, the transaction does not finalize, no state
changes, and the report stays `pending`. Re-triage is free and permissionless, so
a failed attempt is not a dead end.

### Read back the consensus-bound amount

```bash
genlayer call "$BUGBOUNTYX" get_report        --args 1
genlayer call "$BUGBOUNTYX" get_program_stats --args 1
```

Check `payout` against the reward table by hand. For a `high` verdict on the
table above it must be `500`, and `total_paid` must have risen by `500` while
`escrow_bal` fell by `500 + fee`. A `SUCCESS` receipt on a `valid` report is
itself evidence that the amount was consensus-bound — the contract reverts with
`"Payout not bound by consensus"` otherwise.

### Lifecycle and dispute

```bash
# sponsor lifecycle
genlayer write "$BUGBOUNTYX" pause_program  --args 1
genlayer write "$BUGBOUNTYX" resume_program --args 1
genlayer write "$BUGBOUNTYX" close_program  --args 1   # refunds remaining escrow to the sponsor

# dispute: hunter or sponsor only
genlayer write "$BUGBOUNTYX" raise_dispute     --args 1 "severity is understated"
# -> returns dispute_id

# sponsor or owner: back to pending for a fresh consensus round
genlayer write "$BUGBOUNTYX" requeue_disputed  --args 1

# owner only: direct arbitration, permanently recorded
genlayer write "$BUGBOUNTYX" resolve_dispute   --args 1 valid high
```

Do not call `close_program` before capturing the payout evidence: it zeroes
`escrow_bal` and leaves any unclaimed `valid` report unclaimable.

### All read methods

```bash
genlayer call "$BUGBOUNTYX" get_program        --args 1
genlayer call "$BUGBOUNTYX" get_report         --args 1
genlayer call "$BUGBOUNTYX" get_program_reports --args 1 0 20
genlayer call "$BUGBOUNTYX" get_pending_queue  --args 10
genlayer call "$BUGBOUNTYX" get_program_stats  --args 1
genlayer call "$BUGBOUNTYX" get_dispute        --args 1
```

`get_program_reports` and `get_pending_queue` return JSON-encoded arrays as
plain strings, not typed lists. Parse them with `json.loads`.

## Automated equivalent

`scripts/smoke.sh` performs the same sequence and prints every transaction hash.

```bash
# read-only, against an existing deployment
BUGBOUNTYX_CONTRACT="$BUGBOUNTYX" scripts/smoke.sh

# full lifecycle, spends fees, runs real consensus
BUGBOUNTYX_CONTRACT="$BUGBOUNTYX" scripts/smoke.sh --write

# also resolve the dispute (requires the owner account)
ARBITRATE=1 BUGBOUNTYX_CONTRACT="$BUGBOUNTYX" scripts/smoke.sh --write
```

It refuses to run write mode unless the configured network is a real test
network and the named account is active and unlocked.

## Tests

```bash
# offline: pure helpers against adversarial LLM output, no node needed
python3 -m pytest tests/test_normalizer.py -v

# Direct Mode: leader-only, mocked LLM, ~30ms per test
python3 -m pytest tests/direct -v

# full consensus, needs Studio or localnet
gltest tests/integration -v -s
```

The `tests/integration` directory does not exist yet. Direct Mode cannot
exercise validator behaviour, so consensus rejection paths — the core claim of
this contract — are currently only asserted by `scripts/preflight.py`'s static
checks. Adding integration coverage for the reward-mismatch revert and the
hallucinated-duplicate downgrade is the highest-value next test.

## Before submitting

- [ ] `genvm-lint check contracts/BugBountyX.py` passes
- [ ] `python3 scripts/preflight.py` passes
- [ ] `python3 -m pytest tests/ -q` passes
- [ ] deployed to a public testnet
- [ ] `triage_report` receipt in `proof/` shows `MAJORITY_AGREE` / `FINALIZED`
- [ ] contract address and triage transaction hash added to `SUBMISSION.md`
