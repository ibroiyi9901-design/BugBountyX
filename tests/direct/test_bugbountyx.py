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


def test_arbitration_pays_from_the_bound_reward_table(direct_vm, direct_deploy, direct_alice,
                                                      direct_owner):
    """A sponsor must not be able to retier the table between raise_dispute and
    resolve_dispute to change what the arbitration is worth. Without the snapshot
    bound at raise time, zeroing the table here would pay the hunter 0."""
    c = direct_deploy("contracts/BugBountyX.py")
    direct_vm.sender = direct_alice
    c.create_program("P", "scope", 1000, 500, 100, 50)
    c.submit_report(1, "Title number one here",
                    "A sufficiently long description of the finding",
                    "step one, step two, step three", "impact", "high")
    direct_vm.mock_llm(".*", _triage_json("valid", "high", 0, "exploitable"))
    c.triage_report(1)
    assert c.get_report(1)["payout"] == 500

    did = c.raise_dispute(1, "severity is understated")
    assert c.get_report(1)["status"] == "disputed"
    assert c.get_dispute(int(did))["bound_rewards"]["high"] == 500

    # the sponsor zeroes the live table mid-dispute
    c.update_rewards(1, 0, 0, 0, 0)
    assert c.get_program(1)["rewards"]["high"] == 0

    # arbitration is owner-only, and pays the tier bound when the dispute was raised
    direct_vm.sender = direct_owner
    c.resolve_dispute(int(did), "valid", "high")
    r = c.get_report(1)
    assert r["payout"] == 500, "arbitration must pay the tier bound at raise_dispute"
    assert r["severity_ai"] == "high"
    assert c.get_dispute(int(did))["resolved"] is True


def test_closed_program_cannot_be_retiered(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy("contracts/BugBountyX.py")
    direct_vm.sender = direct_alice
    c.create_program("P", "scope", 1000, 500, 100, 50)
    c.close_program(1)
    assert c.get_program(1)["status"] == "closed"
    with direct_vm.expect_revert("Program closed"):
        c.update_rewards(1, 1, 1, 1, 1)
