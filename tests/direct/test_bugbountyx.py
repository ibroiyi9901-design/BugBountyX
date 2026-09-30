"""Direct-mode tests for BugBountyX (leader-only, mocked LLM).

Run: pytest tests/direct -v
Requires: genlayer test fixtures (direct_vm, direct_deploy, direct_alice, ...).
Direct mode exercises deterministic logic; use integration tests for consensus.
"""
import json


def _triage_json(decision="valid", severity="high", dup=0, reason="exploitable"):
    return json.dumps({"decision": decision, "severity": severity,
                       "duplicate_of": dup, "reason": reason})


def test_create_fund_submit(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy("contracts/BugBountyX.py")
    direct_vm.sender = direct_alice
    pid = c.create_program("Vault Bounty", '{"in_scope":["vault"]}',
                           1000, 500, 100, 50)
    assert int(pid) == 1
    rid = c.submit_report(1, "Reentrancy in withdraw",
                          "Withdraw callback allows reentry with full details here",
                          "1. deposit 2. withdraw 3. reenter callback",
                          "funds drainable", "high")
    assert int(rid) == 1
    r = c.get_report(1)
    assert r["status"] == "pending"


def test_triage_valid_pays_when_funded(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy("contracts/BugBountyX.py")
    direct_vm.sender = direct_alice
    c.create_program("Vault Bounty", '{"in_scope":["vault"]}', 1000, 500, 100, 50)
    c.submit_report(1, "Reentrancy in withdraw",
                    "Withdraw callback allows reentry with full details here",
                    "1. deposit 2. withdraw 3. reenter callback",
                    "funds drainable", "high")
    direct_vm.mock_llm(".*", _triage_json("valid", "high", 0, "checked poc"))
    # fund_program is payable in integration; direct mode tops up via cheatcode
    out = c.triage_report(1)
    assert out["decision"] in ("valid", "paid")
    assert out["severity"] == "high"
    assert int(out["payout"]) == 500  # consensus-bound reward_high tier


def test_triage_rejects_hallucinated_duplicate(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy("contracts/BugBountyX.py")
    direct_vm.sender = direct_alice
    c.create_program("P", "scope", 100, 50, 10, 5)
    c.submit_report(1, "Title number one here",
                    "A sufficiently long description of the finding",
                    "step one, step two, step three", "impact", "low")
    # LLM claims duplicate of id 999 which does not exist -> downgraded to valid
    direct_vm.mock_llm(".*", _triage_json("duplicate", "low", 999, "looks same"))
    out = c.triage_report(1)
    assert out["decision"] in ("valid", "paid")


def test_bad_severity_rejected(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy("contracts/BugBountyX.py")
    direct_vm.sender = direct_alice
    c.create_program("P", "scope", 100, 50, 10, 5)
    with direct_vm.expect_revert("Invalid severity"):
        c.submit_report(1, "Title number one here",
                        "A sufficiently long description of the finding",
                        "step one, step two, step three", "impact", "apocalyptic")
