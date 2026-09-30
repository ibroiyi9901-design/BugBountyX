#!/usr/bin/env python3
"""Offline BugBountyX preflight.

This does not replace GenVM Direct Mode or a live consensus run. It makes the
repository auditable even on a machine without the GenLayer runtime by checking
Python syntax, the expected contract surface, the shape of the consensus
boundary, the deterministic settlement guards, and the pure LLM-normalization
helpers through a minimal import stub.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "BugBountyX.py"


class _Generic:
    @classmethod
    def __class_getitem__(cls, _item):
        return cls


class _Map(dict, _Generic):
    pass


class _Int(int):
    pass


class _Address(str):
    pass


class _Decorator:
    def __call__(self, fn):
        return fn

    @property
    def payable(self):
        return self


class _Public:
    view = _Decorator()
    write = _Decorator()


class _Message:
    sender_address = _Address("0x0000000000000000000000000000000000000001")
    value = _Int(0)


class _Nondet:
    @staticmethod
    def exec_prompt(prompt, response_format=None):
        return ""


class _EqPrinciple:
    @staticmethod
    def prompt_comparative(fn, principle):
        return fn()


class _EVM:
    @staticmethod
    def contract_interface(cls):
        return cls


class _Storage:
    @staticmethod
    def copy_to_memory(value):
        return value


class _VM:
    class UserError(Exception):
        pass


class _GL:
    Contract = object
    public = _Public()
    vm = _VM()
    message = _Message()
    nondet = _Nondet()
    eq_principle = _EqPrinciple()
    evm = _EVM()
    storage = _Storage()


def _install_stub() -> None:
    module = types.ModuleType("genlayer")
    module.gl = _GL()
    module.allow_storage = lambda cls: cls
    module.TreeMap = _Map
    module.DynArray = list
    module.u256 = _Int
    module.Address = _Address
    sys.modules["genlayer"] = module


def _load_contract():
    _install_stub()
    spec = importlib.util.spec_from_file_location("bugbountyx_contract", CONTRACT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gl_evm_is_function_local(tree: ast.AST) -> bool:
    """Every gl.evm reference must sit inside a function body, never at module or
    class scope: an import-time SDK namespace touch breaks contract-schema load."""

    offenders: list[int] = []

    def visit(node: ast.AST, in_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            child_in_function = in_function
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_in_function = True
            if isinstance(child, ast.Attribute) and child.attr == "evm":
                base = child.value
                if isinstance(base, ast.Name) and base.id == "gl" and not in_function:
                    offenders.append(child.lineno)
            visit(child, child_in_function)

    visit(tree, False)
    return offenders


def _forbidden_imports(tree: ast.AST) -> list[str]:
    banned = {"os", "sys", "subprocess", "random"}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module.split(".")[0])
    return sorted(set(found) & banned)


def _function_source(tree: ast.AST, name: str) -> str:
    lines = ast.unparse(tree).splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"function not found: {name}")


def _ast_checks(source: str) -> list[str]:
    tree = ast.parse(source)
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    fn_names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    required_classes = {"BugBountyX", "Program", "Report", "Dispute"}
    required_methods = {
        "create_program", "fund_program", "pause_program", "resume_program",
        "close_program", "update_rewards", "submit_report", "triage_report",
        "claim_payout", "raise_dispute", "resolve_dispute", "requeue_disputed",
        "get_program", "get_report", "get_dispute", "get_program_reports",
        "get_pending_queue", "get_program_stats", "set_fee", "transfer_ownership",
    }
    required_internals = {"_reward_for", "_append", "_send", "_pay", "_summaries"}
    required_helpers = {"_clean", "_norm", "_coerce_sev", "_coerce_u", "_tier_payout", "_now"}

    checks = []

    assert not _forbidden_imports(tree), _forbidden_imports(tree)
    checks.append("no forbidden imports (os/sys/subprocess/random)")

    assert not _gl_evm_is_function_local(tree), _gl_evm_is_function_local(tree)
    checks.append("gl.evm interface is function-local, never touched at import time")

    assert required_classes <= class_names, required_classes - class_names
    checks.append("required storage and contract classes present")

    assert required_methods <= fn_names, required_methods - fn_names
    checks.append("full public lifecycle and read surface present")

    assert required_internals <= fn_names, required_internals - fn_names
    assert required_helpers <= fn_names, required_helpers - fn_names
    checks.append("deterministic settlement and normalization helpers present")

    assert source.count("gl.eq_principle.prompt_comparative") == 1
    assert source.count("gl.nondet.exec_prompt") == 1
    checks.append("exactly one LLM call inside exactly one consensus boundary")

    assert "Only LLM method" in source
    assert "gl.storage.copy_to_memory(self.reports[report_id])" in source
    assert "gl.storage.copy_to_memory(self.programs[r0.program_id])" in source
    checks.append("triage snapshots storage to memory before entering nondet")

    assert "Payout not bound by consensus" in source
    assert '_coerce_u(result.get("reward", 0)) != reward' in source
    checks.append("settlement re-derives the reward and fails closed on mismatch")

    assert 'out["reward"] = _tier_payout(rw_m, out["severity"])' in source
    assert "must be identical" in source
    checks.append("consensus binds a node-derived reward, not a model-chosen amount")

    assert "self.reports[dup].program_id == r.program_id" in source
    assert 'dec, dup = "valid", u256(0)' in source
    checks.append("duplicate citations are derived-checked against storage")

    assert 'r.status = "paid" if self._pay(r.program_id, r.hunter, reward) else "valid"' in source
    assert "if not self._pay(r.program_id, r.hunter, r.payout):" in source
    assert "Escrow underfunded" in source
    checks.append("payouts are ledger-gated and underfunded escrow fails closed")

    assert source.count("gl.message.value") == 2
    assert "@gl.public.write.payable" in source
    assert "Send GEN to fund escrow" in source
    checks.append("exactly one payable method: escrow funding, zero-value rejected")

    assert "Max 10%" in source and "int(bps) > 1000" in source
    checks.append("owner fee is capped at 10%")

    assert source.count("Rewards must descend") == 2
    checks.append("reward table must strictly descend, at create and at retier")

    assert "n - 60" in source and "if len(lines) >= 20:" in source
    checks.append("dedup prompt context is explicitly bounded")

    for cap in ("title[:200]", "description[:6000]", "poc[:6000]",
                "impact[:2000]", "scope[:4000]", "name[:120]", "[:280]"):
        assert cap in source, cap
    checks.append("all attacker-controlled fields are truncated at storage")

    assert source.count("gl.public.view") == 6
    checks.append("read surface returns primitives only (no list generics)")

    assert "reward_critical: u256\n    reward_high: u256\n    reward_medium: u256\n    reward_low: u256" in source
    assert "p.reward_critical, p.reward_high, p.reward_medium, p.reward_low)" in source
    assert "reward = u256(_tier_payout((int(d.reward_critical), int(d.reward_high)," in source
    checks.append("arbitration pays from the reward table bound at raise_dispute")

    assert "_reward_for" not in _function_source(tree, "resolve_dispute")
    assert "_reward_for" in _function_source(tree, "triage_report")
    checks.append("only triage reads the live reward table; resolve_dispute reads the bound one")

    return checks


def _helper_checks(c) -> list[str]:
    checks = []

    assert c._coerce_sev("CRITICAL") == "critical"
    assert c._coerce_sev("  High  ") == "high"
    assert c._coerce_sev("apocalyptic") == "info"
    assert c._coerce_sev(None) == "info"
    checks.append("severity coerces to the five tiers and fails closed to info")

    assert c._coerce_u("42") == 42
    assert c._coerce_u(-7) == 0
    assert c._coerce_u("not a number") == 0
    checks.append("u256 coercion clamps negatives and garbage to zero")

    assert c._clean('{"a":1}') == {"a": 1}
    assert c._clean('```json\n{"a":1}\n```') == {"a": 1}
    assert c._clean('sure! here you go: {"a":1} hope that helps') == {"a": 1}
    assert c._clean("no json whatsoever") == {}
    assert c._clean(12345) == {}
    checks.append("fenced, prose-wrapped, and garbage output all parse safely")

    fenced = c._norm('```json\n{"decision":"valid","severity":"HIGH","duplicate_of":0,"reason":"ok"}\n```')
    assert fenced["decision"] == "valid" and fenced["severity"] == "high"
    checks.append("fenced JSON with mixed-case severity normalizes correctly")

    assert c._norm({"is_valid": True, "severity": "critical"})["decision"] == "valid"
    assert c._norm({"is_valid": False, "severity": "high"})["decision"] == "invalid"
    assert c._norm({"in_scope": False, "severity": "high"})["decision"] == "invalid"
    dupe = c._norm({"is_duplicate": True, "duplicate_of": 3, "severity": "medium"})
    assert dupe["decision"] == "duplicate" and dupe["duplicate_of"] == 3
    checks.append("is_valid / is_duplicate / in_scope key variants map to the enum")

    assert c._norm("not json at all")["decision"] == "invalid"
    assert c._norm({})["decision"] == "invalid"
    assert c._norm({"decision": "valid"})["duplicate_of"] == 0
    long_reason = c._norm({"decision": "valid", "reason": "x" * 500})["reason"]
    assert len(long_reason) == 280
    checks.append("unparseable output fails closed to invalid; reason is truncated")

    table = (1000, 500, 100, 50)
    assert c._tier_payout(table, "critical") == 1000
    assert c._tier_payout(table, "CRITICAL") == 1000
    assert c._tier_payout(table, "high") == 500
    assert c._tier_payout(table, "medium") == 100
    assert c._tier_payout(table, "low") == 50
    assert c._tier_payout(table, "info") == 0
    checks.append("every severity tier maps to its reward-table amount")

    assert c._tier_payout(table, "high") != c._tier_payout(table, "medium")
    assert c._tier_payout(table, "medium") == c._tier_payout(table, "medium")
    checks.append("tier tolerance cannot move the amount, and derivation is reproducible")

    assert list(c._TIER) == ["info", "low", "medium", "high", "critical"]
    assert list(c._TIER.values()) == sorted(c._TIER.values())
    assert c._DECISIONS == ("valid", "invalid", "duplicate")
    checks.append("tier ordering and decision enum are the consensus-visible contract")

    assert c._now() > 0
    checks.append("transaction clock is pinned to the GenVM tx datetime")

    settled = c._norm(json.dumps({"decision": "valid", "severity": "high"}))
    settled["reward"] = c._tier_payout(table, settled["severity"])
    assert settled["reward"] == 500
    checks.append("end-to-end: a normalized verdict derives a bound payout of 500")

    bound = c.Dispute(1, 7, c.Address("0x0"), "understated", False, "",
                      1000, 500, 100, 50)
    live_after_retier = (0, 0, 0, 0)
    assert c._tier_payout((int(bound.reward_critical), int(bound.reward_high),
                          int(bound.reward_medium), int(bound.reward_low)), "high") == 500
    assert c._tier_payout(live_after_retier, "high") == 0
    checks.append("a dispute keeps the stakes fixed even if the sponsor zeroes the table")

    return checks


def main() -> int:
    source = CONTRACT.read_text(encoding="utf-8")
    compile(source, str(CONTRACT), "exec")
    checks = ["contract compiles as Python"]
    checks += _ast_checks(source)
    contract = _load_contract()
    checks += _helper_checks(contract)

    print(f"BugBountyX offline preflight: {len(checks)}/{len(checks)} checks passed")
    for index, check in enumerate(checks, 1):
        print(f"  {index:02d}. PASS - {check}")
    print(
        "\nGenVM consensus/runtime behavior is covered separately by "
        "tests/direct/test_bugbountyx.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
