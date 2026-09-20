# Portal submission copy-paste (Intelligent Contracts)

## Contribution Type
Builder → Intelligent Contracts

## Title
BugBountyX — AI-Triaged Bug Bounty Primitive with Comparative Consensus

## Notes / Description (956 chars — paste into the 1000-char box)
BugBountyX is a standalone, reusable GenLayer primitive for decentralized bug
bounties: sponsors open programs with per-severity GEN rewards and payable
escrow, hunters submit structured reports, anyone triggers AI triage, valid
reports auto-pay (fee split hunter/owner), disputes go to owner arbitration.

Consensus lives in exactly one method, triage_report(): leader + validators
independently run the same LLM over identical on-chain inputs (scope, report,
existing valid-report summaries) via gl.nondet.exec_prompt(response_format=
"json"), then gl.eq_principle.prompt_comparative enforces decision-identical /
severity-within-one-tier agreement. No strict_eq on LLM text, no schema-only
checks. Duplicate verdicts are derive-checked against state (cited id must
exist, same program, valid/paid) so hallucinated ids downgrade to valid.

Deterministic intake/settlement, TreeMap+u256 storage, defensive LLM parsing,
paginated views, direct tests included. Ports to freelance/grant/moderation
payouts by swapping the prompt.

## Evidence
- Paste your GitHub repo URL here (contracts/BugBountyX.py + README + tests)
- After deploy, add: explorer link + contract address + a triage_report tx hash
  showing MAJORITY_AGREE / FINALIZED.

## Pre-submit checklist
- [ ] genvm-lint lint passes (done: 3 checks ok, 439 lines, pinned runner)
- [ ] README explains purpose + consensus + state design (done)
- [ ] tests/direct + tests/test_normalizer.py included (done, 3 passing)
- [ ] Deploy to testnet-bradbury/studionet and paste address + tx as evidence
