# Portal submission copy-paste (Intelligent Contracts)

## Contribution Type
Builder → Intelligent Contracts

## Title
BugBountyX — AI-Triaged Bug Bounty Primitive with Comparative Consensus

## Notes / Description (985 chars — paste into the 1000-char box)
BugBountyX is a standalone GenLayer primitive for decentralized bug bounties:
sponsors open programs with per-severity GEN rewards and escrow, hunters submit
reports, anyone triggers AI triage, valid reports auto-pay, disputes go to owner
arbitration.

Consensus lives in one method, triage_report(): leader + validators run the
same LLM over identical on-chain inputs (scope, report, valid-report summaries)
via gl.nondet.exec_prompt, then gl.eq_principle.prompt_comparative enforces an
identical decision, matching duplicate id, severity within one tier, and an
identical derived reward: each derives the GEN amount from the reward
table, so tier-tolerant verdicts can never transfer different amounts;
settlement re-derives it and reverts on mismatch. Duplicate verdicts
are derive-checked against state, so hallucinated ids downgrade to valid.

Deterministic intake/settlement, TreeMap+u256 storage, defensive LLM parsing,
direct tests. Ports to freelance/grant/moderation payouts.

## Evidence
- Repo: https://github.com/ibroiyi9901-design/BugBountyX (contracts/BugBountyX.py + docs + tests + scripts)
- Deployed (official): `0x82Bf017B38A4A4576b92A0442c33e79927F21298` on StudioNet
  https://explorer-studio.genlayer.com/address/0x82Bf017B38A4A4576b92A0442c33e79927F21298
- Deploy tx: `0x8933c4cf92ebc9080fbe33d43ce41062930d97d0991dd81855ae5e9675c76089` (FINALIZED, 3 agree / 2 idle)
- Additional identical-source deployment: `0x196b9a827ab4c616AD5210E6f9A9CD09a242D1d0`
  https://explorer-studio.genlayer.com/address/0x196b9a827ab4c616AD5210E6f9A9CD09a242D1d0
  Studio import: https://studio.genlayer.com/?import-contract=0x196b9a827ab4c616AD5210E6f9A9CD09a242D1d0
  deploy tx `0x6b9a90f4f8f621ff74f1ae74aa7841ce4445fa3a16ab443d9ab0041d6582e3b9`
  (FINALIZED, 5/5 validators agree); same source, sha256 `143a41e0…3f01`
- Deployed source is byte-identical to `contracts/BugBountyX.py`,
  sha256 `143a41e082289279223be283384b9c862eee6eaa345d4d3e9890194ba9273f01`
  (reproduce via `gen_getContractCode`; see proof/source-verification.json)
- STILL NEEDED: a `triage_report` tx hash showing MAJORITY_AGREE / FINALIZED.
  The deployment is live but unused, so no report has ever been triaged. Run
  `scripts/smoke.sh --write` against the address above to produce it.

## Pre-submit checklist
- [ ] genvm-lint check passes (lint ok + validation ok, 502 lines, pinned runner)
      run as: `GENVM_VERSION=v0.3.0-rc7 genvm-lint check contracts/BugBountyX.py`
- [ ] README explains purpose + consensus + state design (done)
- [ ] tests pass: `python3.12 -m pytest tests/ -q` (10 passed)
- [ ] Deploy to testnet-bradbury/studionet and paste address + tx as evidence
