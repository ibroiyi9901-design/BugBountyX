# Proof directory

## What is captured

Sanitized extracts of observed GenLayer StudioNet receipts and state reads.
Nothing here is reconstructed, simulated, or hand-written. Every file was
produced by querying the live network.

| File | What it proves |
|---|---|
| `official-deployment.json` | The live deployment: address, deploy transaction, creator, finalization, and ABI shape |
| `source-verification.json` | The deployed source is **byte-identical** to `contracts/BugBountyX.py`, with the sha256 and the RPC calls to reproduce it |
| `empty-state-reads.json` | The live state, which is **empty** — no program, report, dispute, or escrow |

## The official deployment

```text
network     studionet (GenLayer Studio Network)
address     0x82Bf017B38A4A4576b92A0442c33e79927F21298
deploy tx   0x8933c4cf92ebc9080fbe33d43ce41062930d97d0991dd81855ae5e9675c76089
creator     0x37cDbd86743e2b80486413E89ca4c70A58147889
created     2026-09-30T10:44:07.824804+00:00
status      FINALIZED, leader SUCCESS, 3 agree / 2 idle
ABI         20 methods - 6 view, 14 write, 1 payable
```

Studio: <https://studio.genlayer.com/?import-contract=0x82Bf017B38A4A4576b92A0442c33e79927F21298>
Explorer: <https://explorer-studio.genlayer.com/address/0x82Bf017B38A4A4576b92A0442c33e79927F21298>

Two of five StudioNet validators were idle and cast no vote. Finalization
required three agreements and got exactly three, so the margin is the minimum
Studio permits. The leader and all three agreeing validators returned
`execution_result: 'SUCCESS'`.

## Source verification

The deployed contract is byte-identical to the file in this repository at commit
`acab99c`:

```text
sha256  143a41e082289279223be283384b9c862eee6eaa345d4d3e9890194ba9273f01
bytes   23262
lines   502
```

Reproduce it without the CLI:

```bash
ADDR=0x82Bf017B38A4A4576b92A0442c33e79927F21298
curl -s -X POST https://explorer-studio.genlayer.com/api \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"gen_getContractCode\",\"params\":[\"$ADDR\"]}" \
  | python3 -c 'import sys,json,base64; sys.stdout.write(base64.b64decode(json.load(sys.stdin)["result"]).decode())' \
  | sha256sum

sha256sum contracts/BugBountyX.py
```

The deployed ABI also carries `get_dispute`, which only exists in the current
source. That is a second, independent confirmation that this deployment is the
post-fix build and not an earlier revision.

## The gap: no consensus evidence yet

This deployment has **never been used**. Every record read reverts with
`exit_code 1` (a `TreeMap` read of an absent key), and `get_pending_queue(10)`
returns `[]`.

So there is **no `triage_report` receipt** for this address, and no evidence that
the comparative-equivalence path has ever run against real validators. The
contract being deployed and its source matching says nothing about whether
`triage_report` reaches consensus and settles a correct payout.

Producing that evidence is the remaining work:

```bash
export BUGBOUNTYX=0x82Bf017B38A4A4576b92A0442c33e79927F21298
BUGBOUNTYX_CONTRACT="$BUGBOUNTYX" scripts/smoke.sh --write
```

That opens a program, funds escrow, submits a report, and runs real consensus on
`triage_report`, printing each transaction hash.

## What a valid triage receipt must demonstrate

Once that run exists, a reviewer should be able to confirm:

1. `status_name: 'FINALIZED'` with `execution_result: 'SUCCESS'`. Acceptance is
   not finalization, and finalization is not successful execution — a
   transaction can finalize carrying an error.
2. Consensus reported a majority agreement rather than a leader-only result.
3. The recorded `payout` equals the reward table's amount for the recorded
   `severity_ai`. This is checkable by hand, and it is the whole point: the
   contract reverts with `"Payout not bound by consensus"` if the settled amount
   disagrees with the consensus-derived amount, so a `SUCCESS` receipt on a
   `valid` report is itself evidence that the amount was consensus-bound.
4. `total_paid` rose by that amount while `escrow_bal` fell by it plus the fee.

Point 3 is the one worth demonstrating explicitly, because it is the claim that
distinguishes this contract from a thin LLM wrapper.

## What is not here, and why

- **No raw RPC dumps.** The `raw-*` convention is unused; only summarized,
  labelled extracts were kept.
- **No fabricated lifecycle evidence.** Earlier drafts of this directory
  described `final-*` and `raw-*` files from a superseded deployment. Those did
  not exist for this contract and were not created.
- **No validator keys, tokens, or machine-local configuration.** Validator
  addresses in the deployment receipt are public on-chain identities.

## Naming convention

For future captures, so multiple deployments can coexist:

```text
<network>-<UTC timestamp>-<method>.json
```

for example `studionet-2026-09-30-15-04-22-triage_report.json`.
