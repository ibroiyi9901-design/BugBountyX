# BugBountyX Architecture

## Design objective

BugBountyX is designed as a reusable escrowed-judgment primitive, not as a policy application or a marketing demo.

The contract owns escrow, a severity reward table, structured report intake, adjudication state, and dispute arbitration. Exactly one question is delegated to GenLayer consensus: *is this report in scope, is it a duplicate, and how severe is it?* Everything else — money, lifecycle, and authorization — is deterministic.

## Layer separation

BugBountyX has three layers.

### Layer 1: deterministic intake and escrow

A sponsor opens a program with a scope document and a descending reward table, then funds it with GEN. A hunter submits a structured report: title, description, proof of concept, impact, and a claimed severity.

None of this uses an LLM. Intake is cheap, censorship-resistant, and identical on every node, so a sponsor cannot argue that a report "was never really submitted" and a hunter cannot be front-run by a leader that decides not to accept their work.

Claims are bounded at intake, not after the fact: title ≥ 8 chars, description ≥ 20 chars, PoC ≥ 10 chars, and a severity string that must already be one of the five tiers. Anything else reverts before storage, so a report that reaches consensus is always well-formed.

### Layer 2: consensus adjudication

One method, `triage_report(report_id)`, is nondeterministic. It is grounded in on-chain inputs only — program scope, the report, and a bounded summary of prior `valid`/`paid` reports in the same program — and it is decided by `gl.eq_principle.prompt_comparative`. See [`CONSENSUS.md`](./CONSENSUS.md).

The consensus output is deliberately narrow: a `decision` enum, a `severity` tier, a cited `duplicate_of` id, a one-line reason, and a `reward` that is *derived* from the severity and the program's reward table rather than produced by the model.

### Layer 3: deterministic settlement

After consensus returns, ordinary code applies the verdict. It re-derives the reward from stored tiers, requires it to equal the consensus `reward`, downgrades unverifiable duplicate citations, moves escrow, splits the fee, and writes final status.

This keeps financial authority outside the model. A model can propose a verdict; it cannot choose an amount that the reward table does not already authorize.

## Program and report lifecycle

```text
create_program
      |
      v
  active  (escrow_bal = 0)
      |
      +--> fund_program ......... escrow_bal += msg.value
      |
      +--> pause_program ....... paused   (no new reports)
      |        |
      |        +--> resume_program ... active
      |
      +--> close_program ....... closed   (remaining escrow refunded to sponsor)
      |
      v
  submit_report ......................... report: pending
      |
      v
  triage_report  ......................... consensus
      |
      +--> invalid ....................... report: invalid      (no payout)
      |
      +--> duplicate (verified) .......... report: duplicate   (no payout)
      |
      +--> valid, reward = 0 ............ report: valid        (no payout)
      |
      +--> valid, escrow funded .......... report: paid         (auto-pay)
      |
      +--> valid, escrow short .......... report: valid        (claimable later)
                |
                +--> claim_payout ........ report: paid
      |
      +--> raise_dispute (hunter/sponsor) report: disputed
                |                            dispute snapshot: reward table bound here
                |
                +--> resolve_dispute (owner) ... report: valid | invalid | duplicate
                |                                 pays from the BOUND table, not the live one
                |
                +--> requeue_disputed (owner/sponsor) ... report: pending
```

## Why a dispute snapshots the reward table

`raise_dispute` copies the program's four reward tiers into the `Dispute` record, and `resolve_dispute` pays from that snapshot.

The alternative — reading the live table at resolution time — lets the sponsor change the stakes after the dispute is open. Zeroing the table between `raise_dispute` and `resolve_dispute` would turn a valid finding into a `0` payout, and the sponsor would have committed no rule violation: every call would be authorized.

Binding the table at raise time makes the arbitration's value fixed the moment the contest starts, and the bound table is readable through `get_dispute`. Retiering remains free for the sponsor; it simply cannot reach back into an open dispute.

This is why the live reward table is read in exactly one place in the contract: `triage_report`, as part of the consensus-bound derivation.

## Why the reward is consensus-bound, not model-chosen

Severity is graded. A validator set can reasonably agree that one report is `high` and another says `medium` — the same risk band, one tier apart. That tolerance is desirable for the *label*.

It is unacceptable for the *transfer*. A tier-tolerant verdict that moved GEN would mean the amount paid depended on which validator happened to be more confident.

BugBountyX therefore makes the amount a deterministic function of the label:

```text
_tier_payout(reward_table, severity) -> GEN amount
```

Every node derives `reward` itself from the same severity and the same stored table, and the equivalence principle requires that derived `reward` to be **identical** across leader and validators. Settlement then recomputes it from the stored tiers and reverts with `"Payout not bound by consensus"` on any mismatch.

A validator cannot widen the payout, and it cannot disagree about the payout without failing consensus.

## Why duplicate citations are derived-checked

`duplicate_of` is the one field where the model names an object in the world rather than describing one. A hallucinated id is not a formatting problem: it silently denies a real hunter their payout.

Settlement therefore refuses to trust it. A duplicate citation survives only if the id exists, belongs to the same program, is currently `valid` or `paid`, and is not the report itself. Anything else is downgraded to `valid` — the payout-preserving direction.

The consequence is that a *hallucinated* duplicate can never lose money, and a *real* duplicate can only ever cost the duplicating hunter, who can dispute.

## Bounded dedup context

`_summaries` is the only place prior state influences the model, so it is bounded twice: it walks at most the last 60 reports in the program and emits at most 20 lines, each restricted to `id | title | severity` for reports that are `valid` or `paid`.

This keeps the prompt small and deterministic in shape. It also means dedup is *recent-validity* dedup, not a complete historical search — a deliberate trade: a hunter whose finding duplicates something older than the window is protected by the dispute path rather than by the prompt.

## State design

- Counters: `next_program_id`, `next_report_id`, `next_dispute_id` — `u256`, starting at 1, so `0` is an unambiguous "none".
- Primary maps: `programs`, `reports`, `disputes` — `TreeMap[u256, Struct]`. A `Dispute` carries the reward table bound at raise time, so the arbitration is self-contained.
- Append-only indexes, no nested generics:
  - `program_report_counts[pid]` + `program_report_index["pid:idx"] -> rid`
  - `hunter_report_counts[addr]` + `hunter_report_index["addr:idx"] -> rid`
- Money: per-program `escrow_bal` `u256` ledger. The contract's pooled `balance` holds the GEN; the ledger is what prevents overspend.

The design keeps all storage to `TreeMap` of `@allow_storage` dataclasses of `u256`/`str`/`Address`/`bool`. `dict`, `list`, and `float` never touch storage; `dict` is used only as a method return type and `list` only as a local.

## Complexity bound

| Operation | Cost |
|---|---|
| `create_program` / `fund_program` / lifecycle | O(1) |
| `submit_report` | O(1) — counter plus two index appends |
| `triage_report` | O(1) model calls; prompt context ≤ 20 lines from ≤ 60 reports |
| `claim_payout` / `raise_dispute` / `resolve_dispute` | O(1) |
| `get_program` / `get_report` / `get_dispute` | O(1) |
| `get_program_reports` / `get_pending_queue` | bounded page (≤ 50 ids) |
| `get_program_stats` | O(reports in program) — read-only, not on a money path |

Consensus cost is constant per triage: one `exec_prompt` per node and one comparative equivalence check. Unlike a pairwise semantic graph, BugBountyX's model usage does not grow with program size.

## ABI discipline

Two views, `get_program_reports` and `get_pending_queue`, return a JSON-encoded array as a plain `str` rather than a typed list. Unspecialized list generics in the return position break contract-schema load in Studio, and these are the only two list-shaped reads. Keeping the ABI to primitives is a deliberate compatibility constraint, documented in the code at both sites.
