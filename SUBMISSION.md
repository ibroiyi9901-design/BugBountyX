# Portal submission copy-paste (Intelligent Contracts)

## Contribution Type
Builder → Intelligent Contracts

## Title
BugBountyX — AI-Triaged Bug Bounty Primitive with Comparative Consensus

## Notes / Description (988 chars — paste into the 1000-char box)
BugBountyX is a standalone GenLayer primitive for decentralized bug bounties:
sponsors open programs with per-severity GEN rewards and escrow, hunters submit
reports, anyone triggers AI triage, valid reports auto-pay, disputes go to owner
arbitration.

Consensus lives in one method, triage_report(): leader + validators run the
same LLM over identical on-chain inputs (scope, report, valid-report summaries)
via gl.nondet.exec_prompt, then gl.eq_principle.prompt_comparative enforces an
identical decision, matching duplicate id, severity within one tier, and an
identical derived reward: each node derives the GEN amount from severity and
the reward table, so tier-tolerant verdicts can never transfer different
amounts; settlement re-derives it and reverts on mismatch. Duplicate verdicts
are derive-checked against state, so hallucinated ids downgrade to valid.

Deterministic intake/settlement, TreeMap+u256 storage, defensive LLM parsing,
direct tests. Ports to freelance/grant/moderation payouts.

Deterministic intake/settlement, TreeMap+u256 storage, defensive LLM parsing,
paginated views, direct tests included. Ports to freelance/grant/moderation
payouts by swapping the prompt.

## Evidence
- Paste your GitHub repo URL here (contracts/BugBountyX.py + README + tests)
- After deploy, add: explorer link + contract address + a triage_report tx hash
  showing MAJORITY_AGREE / FINALIZED.

## Pre-submit checklist
- [ ] genvm-lint check passes (lint ok + validation ok, 480 lines, pinned runner)
      run as: `GENVM_VERSION=v0.3.0-rc7 genvm-lint check contracts/BugBountyX.py`
- [ ] README explains purpose + consensus + state design (done)
- [ ] tests pass: `python3.12 -m pytest tests/ -q` (8 passed)
- [ ] Deploy to testnet-bradbury/studionet and paste address + tx as evidence
