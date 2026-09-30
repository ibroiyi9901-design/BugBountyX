# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""BugBountyX: AI-triaged bug-bounty primitive. Sponsor funds escrow, hunter
submits reports, validators reach LLM consensus (comparative eq. principle),
valid reports auto-pay, owner arbitrates disputes. Payout math is deterministic."""
from dataclasses import dataclass
from genlayer import *
from datetime import datetime, timezone
import json
# NOTE: no top-level gl.evm / contract-interface blocks here on purpose.
# Studio builds the ABI by importing this module; anything touching versioned
# SDK namespaces at import time breaks schema load. The EOA payout interface
# is therefore defined lazily inside _send (runtime only, never import time).
_TIER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_DECISIONS = ("valid", "invalid", "duplicate")
def _coerce_sev(v: object) -> str:
    s = str(v if v is not None else "info").strip().lower()
    return s if s in _TIER else "info"
def _coerce_u(v: object) -> u256:
    try:
        n = int(str(v).strip())
    except Exception:
        return u256(0)
    return u256(n) if n >= 0 else u256(0)
def _clean(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    t = raw.replace("```json", "").replace("```", "").strip()
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        t = t[a:b + 1]
    try:
        d = json.loads(t)
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}
def _norm(raw: object) -> dict:  # pure: runs on leader + every validator
    d = _clean(raw)
    dec = str(d.get("decision", "")).strip().lower()
    if dec not in _DECISIONS:  # tolerate is_valid/is_duplicate style outputs
        if d.get("is_duplicate") is True:
            dec = "duplicate"
        elif d.get("is_valid") is False or d.get("in_scope") is False:
            dec = "invalid"
        elif d.get("is_valid") is True:
            dec = "valid"
        else:
            dec = "invalid"
    return {"decision": dec, "severity": _coerce_sev(d.get("severity", "info")),
            "duplicate_of": _coerce_u(d.get("duplicate_of", 0)),
            "reason": str(d.get("reason", ""))[:280]}
def _tier_payout(rw: tuple, sev: object) -> int:
    """Reward the program pays for a severity tier. Pure: leader and every
    validator derive it from the same reward table, so `prompt_comparative`
    can bind the exact GEN amount even when severity is only tier-tolerant.
    Independent of `decision` so deterministic downgrades (hallucinated
    duplicate -> valid) stay inside the consensus-bound amount."""
    s = _coerce_sev(sev)
    if s == "critical":
        return int(rw[0])
    if s == "high":
        return int(rw[1])
    if s == "medium":
        return int(rw[2])
    if s == "low":
        return int(rw[3])
    return 0
def _now() -> u256:
    """Transaction timestamp: the GenVM clock is pinned to the tx datetime, so
    leader and validators read the same value. There is no block context."""
    return u256(int(datetime.now(timezone.utc).timestamp()))
@allow_storage
@dataclass
class Program:
    id: u256
    sponsor: Address
    name: str
    scope: str
    reward_critical: u256
    reward_high: u256
    reward_medium: u256
    reward_low: u256
    escrow_bal: u256
    status: str  # active | paused | closed
    created_at: u256
@allow_storage
@dataclass
class Report:
    id: u256
    program_id: u256
    hunter: Address
    title: str
    description: str
    poc: str
    impact: str
    severity_claimed: str
    severity_ai: str
    status: str  # pending|valid|paid|invalid|duplicate|disputed
    duplicate_of: u256  # 0 = none
    payout: u256
    submitted_at: u256
    resolved_at: u256
    triage_reason: str
@allow_storage
@dataclass
class Dispute:
    id: u256
    report_id: u256
    raised_by: Address
    reason: str
    resolved: bool
    outcome: str
class BugBountyX(gl.Contract):
    owner: Address
    fee_bps: u256
    next_program_id: u256
    next_report_id: u256
    next_dispute_id: u256
    programs: TreeMap[u256, Program]
    reports: TreeMap[u256, Report]
    disputes: TreeMap[u256, Dispute]
    program_report_counts: TreeMap[u256, u256]
    program_report_index: TreeMap[str, u256]  # "pid:idx" -> rid
    hunter_report_counts: TreeMap[Address, u256]
    hunter_report_index: TreeMap[str, u256]  # "addr:idx" -> rid
    def __init__(self):
        self.owner = gl.message.sender_address
        self.fee_bps = u256(200)
        self.next_program_id = u256(1)
        self.next_report_id = u256(1)
        self.next_dispute_id = u256(1)
    def _reward_for(self, pid: u256, sev: str) -> u256:
        p = self.programs[pid]
        s = _coerce_sev(sev)
        if s == "critical":
            return p.reward_critical
        if s == "high":
            return p.reward_high
        if s == "medium":
            return p.reward_medium
        if s == "low":
            return p.reward_low
        return u256(0)
    def _append(self, pid: u256, rid: u256, hunter: Address) -> None:
        pi = self.program_report_counts.get(pid, u256(0))
        self.program_report_index[f"{int(pid)}:{int(pi)}"] = rid
        self.program_report_counts[pid] = pi + u256(1)
        hi = self.hunter_report_counts.get(hunter, u256(0))
        self.hunter_report_index[f"{str(hunter)}:{int(hi)}"] = rid
        self.hunter_report_counts[hunter] = hi + u256(1)
    def _send(self, to: Address, amount: u256) -> None:
        # Lazy interface: evaluated at payout runtime, never at import/schema.
        @gl.evm.contract_interface
        class _To:
            class View:
                pass
            class Write:
                pass
        _To(to).emit_transfer(value=amount)

    def _pay(self, pid: u256, hunter: Address, amount: u256) -> bool:
        if amount == u256(0):
            return False
        p = self.programs[pid]
        if p.escrow_bal < amount:
            return False
        fee = (int(amount) * int(self.fee_bps)) // 10000
        to_hunter = int(amount) - fee
        p.escrow_bal = u256(int(p.escrow_bal) - int(amount))
        self.programs[pid] = p
        if to_hunter > 0:
            self._send(hunter, u256(to_hunter))
        if fee > 0:
            self._send(self.owner, u256(fee))
        return True
    def _summaries(self, pid: u256, exclude: u256) -> str:
        n = int(self.program_report_counts.get(pid, u256(0)))
        lines: list[str] = []
        for i in range(max(0, n - 60), n):
            if len(lines) >= 20:
                break
            rid = self.program_report_index.get(f"{int(pid)}:{i}", u256(0))
            if rid == u256(0) or rid == exclude:
                continue
            r = self.reports[rid]
            if r.status in ("valid", "paid"):
                sev = r.severity_ai if r.severity_ai else r.severity_claimed
                lines.append(f"[{int(rid)}] {r.title} | {sev}")
        return "\n".join(lines) if lines else "None"
    @gl.public.write
    def create_program(self, name: str, scope: str, reward_critical: u256,
                       reward_high: u256, reward_medium: u256, reward_low: u256) -> u256:
        if not name.strip() or not scope.strip():  # [EXPECTED] bad input
            raise gl.vm.UserError("Name and scope required")
        vals = (int(reward_critical), int(reward_high), int(reward_medium), int(reward_low))
        if any(v < 0 for v in vals):
            raise gl.vm.UserError("Rewards must be >= 0")
        if not (vals[0] >= vals[1] >= vals[2] >= vals[3]):
            raise gl.vm.UserError("Rewards must descend critical>=high>=medium>=low")
        pid = self.next_program_id
        self.programs[pid] = Program(pid, gl.message.sender_address, name[:120],
            scope[:4000], reward_critical, reward_high, reward_medium, reward_low,
            u256(0), "active", _now())
        self.program_report_counts[pid] = u256(0)
        self.next_program_id = pid + u256(1)
        return pid
    @gl.public.write.payable
    def fund_program(self, program_id: u256) -> None:
        if program_id not in self.programs:  # [EXPECTED]
            raise gl.vm.UserError("Program not found")
        p = self.programs[program_id]
        if p.sponsor != gl.message.sender_address:
            raise gl.vm.UserError("Only sponsor funds")
        if p.status != "active":
            raise gl.vm.UserError("Program not active")
        if gl.message.value == u256(0):
            raise gl.vm.UserError("Send GEN to fund escrow")
        p.escrow_bal = u256(int(p.escrow_bal) + int(gl.message.value))
        self.programs[program_id] = p
    @gl.public.write
    def pause_program(self, program_id: u256) -> None:
        p = self.programs[program_id]
        if p.sponsor != gl.message.sender_address:
            raise gl.vm.UserError("Only sponsor")
        p.status = "paused"
        self.programs[program_id] = p
    @gl.public.write
    def resume_program(self, program_id: u256) -> None:
        p = self.programs[program_id]
        if p.sponsor != gl.message.sender_address:
            raise gl.vm.UserError("Only sponsor")
        if p.status != "paused":
            raise gl.vm.UserError("Not paused")
        p.status = "active"
        self.programs[program_id] = p
    @gl.public.write
    def close_program(self, program_id: u256) -> None:
        p = self.programs[program_id]
        if p.sponsor != gl.message.sender_address:
            raise gl.vm.UserError("Only sponsor")
        bal = int(p.escrow_bal)
        p.status = "closed"
        p.escrow_bal = u256(0)
        self.programs[program_id] = p
        if bal > 0:
            self._send(p.sponsor, u256(bal))
    @gl.public.write
    def update_rewards(self, program_id: u256, reward_critical: u256, reward_high: u256,
                       reward_medium: u256, reward_low: u256) -> None:
        p = self.programs[program_id]
        if p.sponsor != gl.message.sender_address:
            raise gl.vm.UserError("Only sponsor")
        vals = (int(reward_critical), int(reward_high), int(reward_medium), int(reward_low))
        if not (vals[0] >= vals[1] >= vals[2] >= vals[3]):
            raise gl.vm.UserError("Rewards must descend")
        p.reward_critical, p.reward_high, p.reward_medium, p.reward_low = \
            reward_critical, reward_high, reward_medium, reward_low
        self.programs[program_id] = p
    @gl.public.write
    def submit_report(self, program_id: u256, title: str, description: str,
                      poc: str, impact: str, severity: str) -> u256:
        if program_id not in self.programs:  # [EXPECTED]
            raise gl.vm.UserError("Program not found")
        if self.programs[program_id].status != "active":
            raise gl.vm.UserError("Program not active")
        sev = _coerce_sev(severity)
        if severity.strip().lower() != sev:
            raise gl.vm.UserError("Invalid severity")
        if len(title.strip()) < 8 or len(description.strip()) < 20 or len(poc.strip()) < 10:
            raise gl.vm.UserError("Title/description/PoC too short")
        rid = self.next_report_id
        hunter = gl.message.sender_address
        self.reports[rid] = Report(rid, program_id, hunter, title[:200],
            description[:6000], poc[:6000], impact[:2000], sev, "", "pending",
            u256(0), u256(0), _now(), u256(0), "")
        self._append(program_id, rid, hunter)
        self.next_report_id = rid + u256(1)
        return rid
    @gl.public.write
    def triage_report(self, report_id: u256) -> dict:
        """AI triage with comparative consensus. Anyone may call. Only LLM method."""
        if report_id not in self.reports:  # [EXPECTED]
            raise gl.vm.UserError("Report not found")
        r0 = gl.storage.copy_to_memory(self.reports[report_id])
        if r0.status != "pending":
            raise gl.vm.UserError("Already triaged")
        p0 = gl.storage.copy_to_memory(self.programs[r0.program_id])
        if p0.status == "closed":
            raise gl.vm.UserError("Program closed")
        scope_m, title_m, desc_m = p0.scope, r0.title, r0.description
        poc_m, impact_m, claimed_m = r0.poc, r0.impact, r0.severity_claimed
        existing_m = self._summaries(r0.program_id, report_id)
        rw_m = (int(p0.reward_critical), int(p0.reward_high),
                int(p0.reward_medium), int(p0.reward_low))
        def triage_fn() -> dict:
            prompt = ("You are a senior security researcher triaging a bug bounty.\n"
                f"SCOPE:\n{scope_m}\nREPORT:\nTitle: {title_m}\nDesc: {desc_m}\n"
                f"PoC: {poc_m}\nImpact: {impact_m}\nClaimed: {claimed_m}\n"
                f"EXISTING VALID (id|title|sev):\n{existing_m}\n"
                "Decide scope/validity/dupe-id(0 if none)/severity.\n"
                'ONLY JSON: {"decision":"valid|invalid|duplicate",'
                '"severity":"critical|high|medium|low|info",'
                '"duplicate_of":0,"reason":"one line"}')
            out = _norm(gl.nondet.exec_prompt(prompt, response_format="json"))
            out["reward"] = _tier_payout(rw_m, out["severity"])
            return out
        result = gl.eq_principle.prompt_comparative(triage_fn,
            "The `decision` must be identical. If duplicate, `duplicate_of` must "
            "match. `severity` may differ by at most one tier but same risk band, "
            "and `reward` — the GEN the program pays for that severity per its "
            "reward table — must be identical: verdicts that would pay different "
            "amounts are not equivalent.")
        r = self.reports[report_id]  # deterministic settlement below
        dec, sev = str(result.get("decision", "invalid")), _coerce_sev(result.get("severity", "info"))
        dup, reason, now = _coerce_u(result.get("duplicate_of", 0)), str(result.get("reason", ""))[:280], _now()
        if dec == "duplicate":  # verify cited id, don't trust LLM blindly
            ok = (dup != u256(0) and dup in self.reports
                  and self.reports[dup].program_id == r.program_id
                  and self.reports[dup].status in ("valid", "paid") and dup != report_id)
            if not ok:
                dec, dup = "valid", u256(0)
        if dec == "invalid":
            r.status, r.severity_ai = "invalid", sev
        elif dec == "duplicate":
            r.status, r.severity_ai, r.duplicate_of = "duplicate", sev, dup
        else:
            reward = self._reward_for(r.program_id, sev)
            if _coerce_u(result.get("reward", 0)) != reward:  # fail closed
                raise gl.vm.UserError("Payout not bound by consensus")
            r.severity_ai, r.payout = sev, reward
            if reward == u256(0):
                r.status = "valid"
            else:
                r.status = "paid" if self._pay(r.program_id, r.hunter, reward) else "valid"
        r.triage_reason, r.resolved_at = reason, now
        self.reports[report_id] = r
        return {"report_id": int(report_id), "decision": r.status,
                "severity": r.severity_ai, "payout": int(r.payout)}
    @gl.public.write
    def claim_payout(self, report_id: u256) -> None:
        if report_id not in self.reports:  # [EXPECTED]
            raise gl.vm.UserError("Report not found")
        r = self.reports[report_id]
        if r.status != "valid":
            raise gl.vm.UserError("Nothing claimable")
        if r.payout == u256(0):
            raise gl.vm.UserError("Info findings carry no payout")
        if not self._pay(r.program_id, r.hunter, r.payout):
            raise gl.vm.UserError("Escrow underfunded")
        r.status = "paid"
        self.reports[report_id] = r
    @gl.public.write
    def raise_dispute(self, report_id: u256, reason: str) -> u256:
        if report_id not in self.reports:  # [EXPECTED]
            raise gl.vm.UserError("Report not found")
        r = self.reports[report_id]
        p = self.programs[r.program_id]
        caller = gl.message.sender_address
        if caller != r.hunter and caller != p.sponsor:
            raise gl.vm.UserError("Only hunter or sponsor")
        if r.status not in ("valid", "invalid", "duplicate"):
            raise gl.vm.UserError("Cannot dispute this status")
        if not reason.strip():
            raise gl.vm.UserError("Reason required")
        did = self.next_dispute_id
        self.disputes[did] = Dispute(did, report_id, caller, reason[:1000], False, "")
        self.next_dispute_id = did + u256(1)
        r.status = "disputed"
        self.reports[report_id] = r
        return did
    @gl.public.write
    def resolve_dispute(self, dispute_id: u256, outcome: str, new_severity: str) -> None:
        if gl.message.sender_address != self.owner:  # [EXPECTED] arbitrator
            raise gl.vm.UserError("Only owner arbitrates")
        if dispute_id not in self.disputes:
            raise gl.vm.UserError("Dispute not found")
        d = self.disputes[dispute_id]
        if d.resolved:
            raise gl.vm.UserError("Already resolved")
        o = outcome.strip().lower()
        if o not in ("valid", "invalid", "duplicate"):
            raise gl.vm.UserError("Bad outcome")
        r = self.reports[d.report_id]
        sev = _coerce_sev(new_severity)
        d.resolved, d.outcome = True, o
        if o == "valid":
            reward = self._reward_for(r.program_id, sev)
            r.severity_ai, r.payout, r.duplicate_of = sev, reward, u256(0)
            r.resolved_at = _now()
            r.status = "valid" if reward == u256(0) else ("paid" if self._pay(r.program_id, r.hunter, reward) else "valid")
        else:
            r.status = "invalid" if o == "invalid" else "duplicate"
            r.severity_ai, r.resolved_at = sev, _now()
        self.reports[d.report_id] = r
        self.disputes[dispute_id] = d
    @gl.public.write
    def requeue_disputed(self, report_id: u256) -> None:
        if report_id not in self.reports:  # [EXPECTED]
            raise gl.vm.UserError("Report not found")
        r = self.reports[report_id]
        if r.status != "disputed":
            raise gl.vm.UserError("Not disputed")
        caller = gl.message.sender_address
        if caller != self.owner and caller != self.programs[r.program_id].sponsor:
            raise gl.vm.UserError("Only owner or sponsor")
        r.status, r.triage_reason = "pending", ""
        self.reports[report_id] = r
    @gl.public.view
    def get_program(self, program_id: u256) -> dict:
        p = self.programs[program_id]
        return {"id": int(program_id), "sponsor": str(p.sponsor), "name": p.name,
            "scope": p.scope, "rewards": {"critical": int(p.reward_critical),
            "high": int(p.reward_high), "medium": int(p.reward_medium),
            "low": int(p.reward_low), "info": 0}, "escrow_bal": int(p.escrow_bal),
            "status": p.status, "reports": int(self.program_report_counts.get(program_id, u256(0)))}
    @gl.public.view
    def get_report(self, report_id: u256) -> dict:
        r = self.reports[report_id]
        return {"id": int(report_id), "program_id": int(r.program_id), "hunter": str(r.hunter),
            "title": r.title, "description": r.description, "poc": r.poc, "impact": r.impact,
            "claimed": r.severity_claimed, "severity_ai": r.severity_ai, "status": r.status,
            "duplicate_of": int(r.duplicate_of), "payout": int(r.payout), "reason": r.triage_reason}
    @gl.public.view
    def get_program_reports(self, program_id: u256, offset: u256, limit: u256) -> str:
        # JSON array of report ids. Plain str keeps the ABI to primitives —
        # unspecialized list generics break contract-schema load.
        n = int(self.program_report_counts.get(program_id, u256(0)))
        out: list = []
        for i in range(int(offset), min(n, int(offset) + max(1, min(50, int(limit))))):
            rid = self.program_report_index.get(f"{int(program_id)}:{i}", u256(0))
            if rid != u256(0):
                out.append(int(rid))
        return json.dumps(out)
    @gl.public.view
    def get_pending_queue(self, limit: u256) -> str:
        # JSON array of pending report ids (same ABI reason as above).
        out: list = []
        for i in range(1, int(self.next_report_id)):
            if len(out) >= max(1, min(50, int(limit))):
                break
            rid = u256(i)
            if rid in self.reports and self.reports[rid].status == "pending":
                out.append(i)
        return json.dumps(out)
    @gl.public.view
    def get_program_stats(self, program_id: u256) -> dict:
        n = int(self.program_report_counts.get(program_id, u256(0)))
        valid = invalid = dups = pending = paid_total = 0
        for i in range(n):
            rid = self.program_report_index.get(f"{int(program_id)}:{i}", u256(0))
            if rid == u256(0):
                continue
            st = self.reports[rid].status
            if st in ("valid", "paid"):
                valid += 1
            if st == "paid":
                paid_total += int(self.reports[rid].payout)
            elif st == "invalid":
                invalid += 1
            elif st == "duplicate":
                dups += 1
            elif st in ("pending", "disputed"):
                pending += 1
        p = self.programs[program_id]
        return {"program_id": int(program_id), "total": n, "valid": valid,
            "invalid": invalid, "duplicates": dups, "pending": pending,
            "total_paid": paid_total, "escrow_bal": int(p.escrow_bal)}
    @gl.public.write
    def set_fee(self, bps: u256) -> None:
        if gl.message.sender_address != self.owner:  # [EXPECTED]
            raise gl.vm.UserError("Only owner")
        if int(bps) > 1000:
            raise gl.vm.UserError("Max 10%")
        self.fee_bps = bps
    @gl.public.write
    def transfer_ownership(self, new_owner: str) -> None:
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("Only owner")
        self.owner = Address(new_owner)
