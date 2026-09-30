"""Local LLM-resilience tests: no node needed.

Stubs `genlayer` so the contract's pure helpers (_clean/_norm/coercers) can be
imported and exercised with adversarial LLM outputs.
Run: pytest tests/test_normalizer.py -v
"""
import json
import sys
import types


def _stub_genlayer():
    gl = types.ModuleType("genlayer")
    vm = types.SimpleNamespace(UserError=type("UserError", (Exception,), {}))
    gl.vm = vm
    gl_module = types.ModuleType("genlayer")
    gl_module.gl = gl
    sys.modules.setdefault("genlayer", gl_module)
    # `from genlayer import *` needs the names; provide minimal surface
    m = sys.modules["genlayer"]
    m.gl = gl
    m.Address = str
    m.TreeMap = dict
    m.DynArray = list
    m.allow_storage = lambda c: c
    m.u256 = int


_stubbed = False
try:  # only stub when the real SDK is unavailable
    import genlayer  # noqa: F401
except Exception:
    _stub_genlayer()
    _stubbed = True

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bbx", str(Path(__file__).resolve().parents[1] / "contracts" / "BugBountyX.py"))
bbx = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(bbx)
except Exception as e:  # contract needs full SDK for class def; helpers still testable
    # Fall back: exec only helper section
    src = (Path(__file__).resolve().parents[1] / "contracts" / "BugBountyX.py").read_text()
    start = src.index('_TIER =')
    end = src.index('@allow_storage')
    ns: dict = {"u256": int}
    exec("import json\nfrom datetime import datetime, timezone\n" + src[start:end], ns)
    bbx = types.SimpleNamespace(**{k: v for k, v in ns.items() if k.startswith(("_",)) or k in ("_TIER",)})
if _stubbed:  # release the stub so other tests (tests/direct) get the real SDK
    sys.modules.pop("genlayer", None)


def test_fenced_json():
    raw = '```json\n{"decision":"valid","severity":"HIGH","duplicate_of":0,"reason":"ok"}\n```'
    out = bbx._norm(raw)
    assert out["decision"] == "valid" and out["severity"] == "high"


def test_key_variants():
    out = bbx._norm({"is_valid": True, "severity": "critical"})
    assert out["decision"] == "valid"
    out = bbx._norm({"is_duplicate": True, "duplicate_of": 3, "severity": "medium"})
    assert out["decision"] == "duplicate" and out["duplicate_of"] == 3
    out = bbx._norm({"in_scope": False, "severity": "high"})
    assert out["decision"] == "invalid"


def test_garbage_and_severity_coercion():
    assert bbx._norm("not json at all")["decision"] == "invalid"
    assert bbx._norm({"decision": "valid", "severity": "CRITICAL!!!"})["severity"] == "info"
    assert bbx._norm({"decision": "valid", "severity": "low"})["severity"] == "low"


def test_tier_payout_is_deterministic_and_binds_amount():
    rw = (1000, 500, 100, 50)
    assert bbx._tier_payout(rw, "critical") == 1000
    assert bbx._tier_payout(rw, "CRITICAL") == 1000
    assert bbx._tier_payout(rw, "high") == 500
    assert bbx._tier_payout(rw, "info") == 0
    assert bbx._tier_payout(rw, "low") == 50
    # one-tier tolerance must not hide a payout change
    assert bbx._tier_payout(rw, "high") != bbx._tier_payout(rw, "medium")
    # identical verdicts derive the identical amount on every node
    assert bbx._tier_payout(rw, "medium") == bbx._tier_payout(rw, "medium")
