# GENLAYER SKILLS
AI-native procedures for intelligent contract development and validator operations

## Install

```
1
/plugin marketplace add genlayerlabs/skills
or
codex plugin marketplace add genlayerlabs/skills
2
/plugin install genlayer-dev
or
/plugin install genlayernode
Codex: enable from plugin menu
```

## Build

### Write Contract
Production-quality intelligent contracts with pinned GenVM runner versions

### GenVM Lint
Validate contracts for safety, correctness, and SDK compliance

### Direct Tests
Fast in-memory tests — ~30ms per test, no server required

### Integration Tests
Full consensus validation against real GenLayer environments

### GenLayer CLI
Deploy, interact with, and debug contracts from the terminal

## Operate

### Validator Node Setup
Interactive wizard and triage runbook — from bare Linux to running validator in 20–45 minutes

### Validator Management
Manage validators across testnets — join, fund, set identity, monitor

Contributing: Something wrong or missing? Humans and agents alike are welcome to open a PR.

MIT License | GitHub | Docs | GenLayer

---

## Write Contract

The core skill for building GenLayer intelligent contracts — Python classes that run on GenVM with built-in AI capabilities.

**Critical: Pin the Runner Version**
All GenLayer networks reject py-genlayer:test, py-genlayer:latest, and unversioned runner aliases. Every generated contract must start with a pinned runner dependency header:

```
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
```

test and latest are local-development aliases for GenLayer runtime developers. They may work only in a specially configured local Studio environment with a GenLayer developer environment variable, but they do not work on GenLayer networks and must not appear in generated user contracts.

Before returning any contract code, verify:
- The first line is a pinned Depends runner version hash
- There is no py-genlayer:test
- There is no py-genlayer:latest
- There is no unversioned py-genlayer

**What It Covers**
- Architecture Fit — Decide whether GenLayer should own the consensus/settlement step or whether the work belongs in a frontend/backend/off-chain LLM
- Runner Header — Pinned py-genlayer version hashes are mandatory for GenLayer networks
- Equivalence Principle — The critical decision: strict_eq for deterministic calls, independent verification for LLM/web operations
- Validator Consensus — Schema-only validators are rejected as an anti-pattern; validators must rerun, derive, compare, or verify against source data
- Runner Dependencies — Pin py-genlayer version hashes instead of using test, latest, or unversioned aliases
- Storage Rules — TreeMap instead of dict, DynArray instead of list, u256 for money
- LLM Resilience — Defensive parsing, key variation handling, aggressive coercion, JSON response format
- Cross-Contract Calls — Synchronous reads, async writes with emit(), factory patterns
- Error Classification — [EXPECTED], [EXTERNAL], [TRANSIENT], [LLM_ERROR] each with distinct validator behavior

**Contract Skeleton**
```python
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

@gl.contract
class MyContract:
    owner: Address
    items: TreeMap[str, Item]

    def __init__(self):
        self.owner = gl.message.sender_account

    @gl.public.view
    def get_item(self, item_id: str) -> dict:
        return {"id": item_id}

    @gl.public.write
    def set_item(self, item_id: str, value: str):
        if gl.message.sender_account != self.owner:
            raise gl.UserError("Only owner")
```

**Runner Dependencies**
Always pin a specific runner version hash in the contract's first line. All GenLayer networks reject test, latest, and unversioned runner aliases.

| Contract Type | Dependency |
|---|---|
| Single-file Python | py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6 |
| Multi-file Python package | py-genlayer-multi:06zyvrlivjga0d5jlpdbprksc0pa6jmllxvp8s20hq1l512vh5yk |
| Embeddings / semantic search | Add py-lib-genlayer-embeddings:0bmbm3cyfwxsyh454z53vxqjf47wz2q7smcqp1q4g4a6k2kidnyk before py-genlayer in a Seq block |

**Anti-Patterns**
- py-genlayer:test, py-genlayer:latest, or unversioned py-genlayer — All GenLayer networks reject runner aliases; pin the documented runner version hash
- strict_eq() for LLM calls — LLM outputs are non-deterministic
- Schema-only validators for LLM/web output — format checks do not verify the leader's answer
- prompt_non_comparative for classification/scoring/extraction decisions — use comparative validation because decisions need substantive agreement
- dict / list for storage — use TreeMap / DynArray
- float for money — use atto-scale u256
- Inserting fields in middle of dataclass — always append at END

Part of the genlayer-dev plugin. Install with /plugin install genlayer-dev@genlayerlabs

---

## GenVM Lint
Static analysis and validation for GenLayer intelligent contracts. Always lint before testing.

**Commands**

| Command | What It Does | Speed |
|---|---|---|
| genvm-lint check | Lint + validate (recommended) | ~250ms |
| genvm-lint lint | AST checks only | ~50ms |
| genvm-lint validate | SDK semantic checks | ~200ms |
| genvm-lint schema | Extract ABI | ~100ms |
| genvm-lint typecheck | Pyright/Pylance type checking | ~1s |

**What It Catches**
- Forbidden imports: os, sys, subprocess, random
- Non-deterministic patterns: bare float operations
- Type validity: TreeMap, DynArray, Address usage
- Decorator correctness: @gl.public.view, @gl.public.write
- Storage field types: no dict/list in state

**Agent Workflow**
1. Run check with --json
2. Parse errors
3. Fix iteratively
4. Re-run until ok=true

**Exit Codes**
- 0 — All checks passed
- 1 — Lint or validation errors
- 2 — Contract file not found
- 3 — SDK download failed

Install: pip install genvm-linter

---

## Direct Tests

Fast, in-memory tests for intelligent contracts. No server, no Docker, no consensus — just pure logic testing at ~30ms per test.

**Running Tests**
```
pytest tests/direct/ -v
pytest tests/direct/test_specific.py::test_one -v
```

**Basic Pattern**
```python
def test_set_and_get(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/my_contract.py")
    direct_vm.sender = direct_alice
    contract.set_data("hello")
    result = contract.get_data(direct_alice)
    assert result == "hello"
```

**Fixtures**

| Fixture | Purpose |
|---|---|
| direct_vm | VMContext with cheatcodes |
| direct_deploy | Deploy contract function |
| direct_alice, direct_bob, direct_charlie | Test addresses |
| direct_owner | Owner address |

**Cheatcodes**
- direct_vm.sender = address — Set transaction sender
- direct_vm.expect_revert("msg") — Expect a revert
- direct_vm.prank(address) — Temporary sender change
- direct_vm.snapshot() / revert(id) — State snapshots
- direct_vm.warp("2024-06-01T12:00:00Z") — Time travel
- direct_vm.mock_web(regex, response) — Mock HTTP calls
- direct_vm.mock_llm(regex, response) — Mock LLM calls

**Important**
Direct mode runs the leader function only. Validator logic is not exercised. Use integration tests for consensus validation.

---

## Integration Tests

Run contracts against real GenLayer environments with full consensus validation — leader execution, validator verification, and finalization.

**Running Tests**
```
gltest tests/integration/ -v -s
gltest tests/integration/ -v -s --network localnet
gltest tests/integration/ -v -s --network testnet_bradbury
```

**Test Pattern**
```python
from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded

def test_full_flow():
    factory = get_contract_factory("MyContract")
    contract = factory.deploy(args=[])
    receipt = contract.set_data(args=["hello"]).transact()
    assert tx_execution_succeeded(receipt)
    result = contract.get_data(args=[contract.address]).call()
    assert result == "hello"
```

**Lifecycle vs Execution**
ACCEPTED and FINALIZED are transaction lifecycle states, not proof that contract execution succeeded. A transaction can be accepted and finalized with an execution error, and failed execution applies no state changes. For deploy transactions, failed execution means no contract is created.

Always assert tx_execution_succeeded(receipt) before reading state, checking schema/code, or treating a missing contract as an infrastructure issue.

**Direct vs Integration**

| Aspect | Direct | Integration |
|---|---|---|
| Speed | ~30ms | seconds–minutes |
| Server | No | Yes |
| Consensus | Leader only | Full + validators |
| Write methods | Return values | Return receipts |
| Mocking | Supported | Real calls |

**Environments**
- GLSim — Lightweight, Python natively
- Studio local — Full GenVM, Docker required
- studio.genlayer.com — Hosted, no setup, gasless, rate-limited
- Testnet Bradbury — Real network, funded accounts

**Studio Rate Limits**
studio.genlayer.com enforces per-IP limits: 60 req/min, 1000 req/hr, 10000 req/day. Hitting the limit returns HTTP 429 / -32429; wait for the current window to reset, throttle batch tests, or use localnet for heavy suites.

-32028 means the pending queue is full: up to 32 in-flight transactions per sender, with a separate per-contract cap. Wait for receipts instead of firing deploy/write transactions in parallel.

**When to Use**
- Validating consensus behavior
- Testing real web/LLM interactions
- Smoke tests before deploy to testnet

---

## GenLayer CLI

The command-line interface for deploying, calling, and debugging intelligent contracts across all GenLayer networks.

**Setup**
```
npm install -g genlayer
```

**Core Commands**

| Command | Purpose |
|---|---|
| genlayer deploy --contract file.py | Deploy a contract |
| genlayer call | Read (view) call |
| genlayer write | Write transaction |
| genlayer receipt | Get transaction receipt |
| genlayer schema | View contract ABI |
| genlayer code | View deployed source |

**Network Management**
```
genlayer network set testnet-bradbury
genlayer network info
genlayer network list
```
Networks: localnet, testnet-asimov, testnet-bradbury, mainnet

**Studio Rate Limits**
studionet is gasless but rate-limited per IP: 60 req/min, 1000 req/hr, 10000 req/day. Batch deploy/write scripts can trip HTTP 429 / -32429; wait for the window to reset, throttle submissions, or use localnet for heavy batches.

-32028 indicates the pending-queue cap: up to 32 in-flight transactions per sender, plus a separate per-contract cap. Wait for receipts between batches.

**Debugging Workflow**
1. Get receipt: genlayer receipt <txHash> --stdout --stderr
2. Check execution result; ACCEPTED/FINALIZED can still contain execution errors
3. Check schema: genlayer schema <address>
4. Read source: genlayer code <address>
5. Try read: genlayer call <address> <view_method>
6. Appeal: genlayer appeal <txHash>

**Lifecycle vs Execution**
ACCEPTED and FINALIZED mean the network accepted or finalized the transaction outcome. They do not mean contract code executed successfully. If deploy execution fails, no contract is created, so missing code/schema is expected until the receipt shows execution success.

**Account Management**
```
genlayer account create --name dev1
genlayer account use dev1
genlayer account list
genlayer account send 0x123...abc 10gen
```
