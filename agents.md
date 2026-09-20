# BugBountyX — Intelligent GenLayer Contract
> **Target:** ≤ 500 lines of Python-style GenLayer Intelligent Contract  
> **Chain:** GenLayer Testnet (Ethereum-compatible + LLM execution layer)  
> **Purpose:** Decentralized bug bounty platform where AI agents validate, triage, and auto-pay security reports

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    BugBountyX Platform                      │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────┐  │
│  │ Sponsor  │   │ Hunter   │   │Validator │   │Escrow  │  │
│  │  Agent   │   │  Agent   │   │  Agent   │  │ Agent  │  │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └───┬────┘  │
│       │              │              │              │        │
│       └──────────────┴──────────────┴──────────────┘        │
│                         GenLayer IPC                         │
└─────────────────────────────────────────────────────────────┘
```

### Agent Roles

| Agent | Responsibility |
|---|---|
| **SponsorAgent** | Creates bounty programs, funds escrow, sets scope |
| **HunterAgent** | Submits vulnerability reports with PoC |
| **ValidatorAgent** | AI-powered triage — severity scoring, duplicate detection, validity check |
| **EscrowAgent** | Holds funds, releases payment on consensus, handles disputes |

---

## File Structure

```
bugbountyx/
├── agents.md                 ← this file
├── contracts/
│   └── BugBountyX.py         ← single Intelligent Contract (≤ 500 lines)
├── tests/
│   ├── test_sponsor.py
│   ├── test_hunter.py
│   └── test_validator.py
├── scripts/
│   ├── deploy.py
│   └── seed.py
└── README.md
```

---

## The Contract — `contracts/BugBountyX.py`

```python
# ============================================================
#  BugBountyX Intelligent Contract  |  GenLayer
#  Lines: ~500  |  LLM calls: validator agent only
# ============================================================
from genlayer import *
import json, hashlib
from datetime import datetime

# ── Enums ────────────────────────────────────────────────────
class Severity:
    CRITICAL = "critical"   # payout: 100%
    HIGH     = "high"       # payout: 60%
    MEDIUM   = "medium"     # payout: 30%
    LOW      = "low"        # payout: 10%
    INFO     = "info"       # payout: 0% (no pay)

class ReportStatus:
    PENDING   = "pending"
    VALID     = "valid"
    DUPLICATE = "duplicate"
    INVALID   = "invalid"
    PAID      = "paid"
    DISPUTED  = "disputed"

class ProgramStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"

# ── Storage Types ────────────────────────────────────────────
@dataclass
class Program:
    id:           str
    sponsor:      Address
    name:         str
    scope:        str          # JSON: { in_scope: [...], out_of_scope: [...] }
    rewards:      dict         # { "critical": wei, "high": wei, ... }
    escrow_bal:   u256
    status:       str
    report_count: u256
    created_at:   u256

@dataclass
class Report:
    id:           str
    program_id:   str
    hunter:       Address
    title:        str
    description:  str
    poc:          str          # Proof of Concept steps
    impact:       str
    severity:     str          # hunter-claimed
    ai_severity:  str          # validator output
    status:       str
    duplicate_of: str          # report_id if dup
    payout:       u256
    submitted_at: u256
    resolved_at:  u256

@dataclass
class Dispute:
    id:          str
    report_id:   str
    raised_by:   Address
    reason:      str
    resolved:    bool
    outcome:     str

# ── Main Contract ─────────────────────────────────────────────
@gl.contract
class BugBountyX:

    programs: dict[str, Program]
    reports:  dict[str, Report]
    disputes: dict[str, Dispute]
    program_reports: dict[str, list[str]]   # program_id → [report_ids]
    hunter_reports:  dict[str, list[str]]   # address  → [report_ids]
    owner:    Address
    fee_bps:  u256   # platform fee in basis points (e.g. 200 = 2%)

    # ── Constructor ──────────────────────────────────────────
    def __init__(self):
        self.programs        = {}
        self.reports         = {}
        self.disputes        = {}
        self.program_reports = {}
        self.hunter_reports  = {}
        self.owner           = gl.message.sender
        self.fee_bps         = 200  # 2% default

    # ════════════════════════════════════════════════════════
    #  SPONSOR AGENT — Program Management
    # ════════════════════════════════════════════════════════

    @gl.public.write
    def create_program(
        self,
        name:    str,
        scope:   str,   # JSON string
        rewards: str,   # JSON: {"critical": "1000000000000000000", ...}
    ) -> str:
        pid = self._hash(f"{gl.message.sender}{name}{gl.block.timestamp}")
        reward_map = json.loads(rewards)

        self.programs[pid] = Program(
            id           = pid,
            sponsor      = gl.message.sender,
            name         = name,
            scope        = scope,
            rewards      = reward_map,
            escrow_bal   = 0,
            status       = ProgramStatus.ACTIVE,
            report_count = 0,
            created_at   = gl.block.timestamp,
        )
        self.program_reports[pid] = []
        return pid

    @gl.public.write
    def fund_program(self, program_id: str) -> bool:
        p = self._get_program(program_id)
        assert p.sponsor == gl.message.sender, "Not program sponsor"
        assert p.status == ProgramStatus.ACTIVE, "Program not active"
        p.escrow_bal += gl.message.value
        self.programs[program_id] = p
        return True

    @gl.public.write
    def pause_program(self, program_id: str) -> bool:
        p = self._get_program(program_id)
        assert p.sponsor == gl.message.sender, "Not program sponsor"
        p.status = ProgramStatus.PAUSED
        self.programs[program_id] = p
        return True

    @gl.public.write
    def close_program(self, program_id: str) -> bool:
        p = self._get_program(program_id)
        assert p.sponsor == gl.message.sender, "Not program sponsor"
        p.status = ProgramStatus.CLOSED
        # refund remaining escrow to sponsor
        if p.escrow_bal > 0:
            bal = p.escrow_bal
            p.escrow_bal = 0
            self.programs[program_id] = p
            gl.send_tokens(p.sponsor, bal)
        return True

    @gl.public.write
    def update_rewards(self, program_id: str, rewards: str) -> bool:
        p = self._get_program(program_id)
        assert p.sponsor == gl.message.sender, "Not program sponsor"
        p.rewards = json.loads(rewards)
        self.programs[program_id] = p
        return True

    # ════════════════════════════════════════════════════════
    #  HUNTER AGENT — Report Submission
    # ════════════════════════════════════════════════════════

    @gl.public.write
    def submit_report(
        self,
        program_id:  str,
        title:       str,
        description: str,
        poc:         str,
        impact:      str,
        severity:    str,
    ) -> str:
        p = self._get_program(program_id)
        assert p.status == ProgramStatus.ACTIVE, "Program not active"
        assert severity in [
            Severity.CRITICAL, Severity.HIGH,
            Severity.MEDIUM,   Severity.LOW, Severity.INFO
        ], "Invalid severity"

        rid = self._hash(
            f"{gl.message.sender}{program_id}{title}{gl.block.timestamp}"
        )
        hunter = gl.message.sender

        self.reports[rid] = Report(
            id          = rid,
            program_id  = program_id,
            hunter      = hunter,
            title       = title,
            description = description,
            poc         = poc,
            impact      = impact,
            severity    = severity,
            ai_severity = "",
            status      = ReportStatus.PENDING,
            duplicate_of= "",
            payout      = 0,
            submitted_at= gl.block.timestamp,
            resolved_at = 0,
        )

        self.program_reports[program_id].append(rid)
        addr_key = str(hunter)
        if addr_key not in self.hunter_reports:
            self.hunter_reports[addr_key] = []
        self.hunter_reports[addr_key].append(rid)

        p.report_count += 1
        self.programs[program_id] = p

        # Trigger AI validation immediately (async in GenLayer)
        self._validate_report(rid)

        return rid

    # ════════════════════════════════════════════════════════
    #  VALIDATOR AGENT — AI-Powered Triage (LLM Execution)
    # ════════════════════════════════════════════════════════

    @gl.public.write
    def _validate_report(self, report_id: str) -> None:
        r = self._get_report(report_id)
        p = self._get_program(r.program_id)

        # Gather existing valid reports for duplicate detection
        existing = self._get_program_report_summaries(r.program_id, report_id)

        prompt = f"""
You are a senior security researcher and bug bounty validator.

PROGRAM SCOPE:
{p.scope}

SUBMITTED REPORT:
Title: {r.title}
Description: {r.description}
Proof of Concept: {r.poc}
Impact: {r.impact}
Hunter-claimed Severity: {r.severity}

EXISTING VALID REPORTS IN THIS PROGRAM:
{existing}

TASKS:
1. Is this report IN scope based on program scope? (yes/no)
2. Is this a duplicate of any existing report? If yes, which report_id?
3. Is the vulnerability real and exploitable based on the PoC? (yes/no)
4. What is the correct severity? (critical/high/medium/low/info)
5. One-line reason for your decision.

Respond ONLY in this exact JSON format:
{{
  "in_scope": true,
  "is_duplicate": false,
  "duplicate_of": "",
  "is_valid": true,
  "severity": "high",
  "reason": "..."
}}
"""
        # GenLayer non-deterministic call — runs on validator nodes via LLM
        result_raw = gl.exec_prompt(prompt)

        try:
            result = json.loads(result_raw)
        except Exception:
            # Fallback: mark as pending for manual review
            return

        r = self._get_report(report_id)  # re-fetch (GenLayer async state)

        if not result.get("in_scope") or not result.get("is_valid"):
            r.status      = ReportStatus.INVALID
            r.ai_severity = result.get("severity", Severity.INFO)
            r.resolved_at = gl.block.timestamp

        elif result.get("is_duplicate"):
            r.status      = ReportStatus.DUPLICATE
            r.duplicate_of= result.get("duplicate_of", "")
            r.ai_severity = result.get("severity", r.severity)
            r.resolved_at = gl.block.timestamp

        else:
            severity  = result.get("severity", r.severity)
            payout    = self._calc_payout(r.program_id, severity)
            r.status      = ReportStatus.VALID
            r.ai_severity = severity
            r.payout      = payout
            r.resolved_at = gl.block.timestamp
            # Auto-pay if escrow has funds
            self._release_payment(r, payout)

        self.reports[report_id] = r

    # ════════════════════════════════════════════════════════
    #  ESCROW AGENT — Payment & Fund Management
    # ════════════════════════════════════════════════════════

    def _release_payment(self, report: Report, amount: u256) -> bool:
        if amount == 0:
            return False
        p = self._get_program(report.program_id)
        if p.escrow_bal < amount:
            # Underfunded — mark valid but hold payment
            return False

        fee    = (amount * self.fee_bps) // 10000
        payout = amount - fee

        p.escrow_bal -= amount
        self.programs[report.program_id] = p

        # Pay hunter
        gl.send_tokens(report.hunter, payout)

        # Pay platform fee to owner
        if fee > 0:
            gl.send_tokens(self.owner, fee)

        report.status = ReportStatus.PAID
        self.reports[report.id] = report
        return True

    @gl.public.write
    def manual_release(self, report_id: str) -> bool:
        """Sponsor can manually release payment for VALID but unpaid reports"""
        r = self._get_report(report_id)
        p = self._get_program(r.program_id)
        assert p.sponsor == gl.message.sender, "Not sponsor"
        assert r.status == ReportStatus.VALID, "Report not in VALID state"
        return self._release_payment(r, r.payout)

    @gl.public.write
    def raise_dispute(self, report_id: str, reason: str) -> str:
        r = self._get_report(report_id)
        assert (
            r.hunter == gl.message.sender
            or self._get_program(r.program_id).sponsor == gl.message.sender
        ), "Only hunter or sponsor can dispute"
        assert r.status in [
            ReportStatus.INVALID, ReportStatus.DUPLICATE, ReportStatus.VALID
        ], "Cannot dispute this status"

        did = self._hash(f"{report_id}{gl.message.sender}{reason}")
        self.disputes[did] = Dispute(
            id        = did,
            report_id = report_id,
            raised_by = gl.message.sender,
            reason    = reason,
            resolved  = False,
            outcome   = "",
        )
        r.status = ReportStatus.DISPUTED
        self.reports[report_id] = r
        return did

    @gl.public.write
    def resolve_dispute(
        self, dispute_id: str, outcome: str, new_severity: str
    ) -> bool:
        """Owner (platform) resolves disputes as arbitrator"""
        assert gl.message.sender == self.owner, "Only owner"
        d = self.disputes[dispute_id]
        assert not d.resolved, "Already resolved"

        r = self._get_report(d.report_id)
        p = self._get_program(r.program_id)

        d.resolved = True
        d.outcome  = outcome  # "valid" | "invalid" | "duplicate"

        if outcome == "valid":
            payout    = self._calc_payout(r.program_id, new_severity)
            r.status      = ReportStatus.VALID
            r.ai_severity = new_severity
            r.payout      = payout
            self._release_payment(r, payout)
        elif outcome == "invalid":
            r.status     = ReportStatus.INVALID
            r.resolved_at= gl.block.timestamp
        elif outcome == "duplicate":
            r.status     = ReportStatus.DUPLICATE
            r.resolved_at= gl.block.timestamp

        self.reports[d.report_id] = r
        self.disputes[dispute_id] = d
        return True

    # ════════════════════════════════════════════════════════
    #  READ VIEWS
    # ════════════════════════════════════════════════════════

    @gl.public.view
    def get_program(self, program_id: str) -> dict:
        return self.programs[program_id].__dict__

    @gl.public.view
    def get_report(self, report_id: str) -> dict:
        return self.reports[report_id].__dict__

    @gl.public.view
    def get_dispute(self, dispute_id: str) -> dict:
        return self.disputes[dispute_id].__dict__

    @gl.public.view
    def get_program_reports(self, program_id: str) -> list:
        return self.program_reports.get(program_id, [])

    @gl.public.view
    def get_hunter_reports(self, hunter: str) -> list:
        return self.hunter_reports.get(hunter, [])

    @gl.public.view
    def get_program_stats(self, program_id: str) -> dict:
        p       = self._get_program(program_id)
        rids    = self.program_reports.get(program_id, [])
        valid   = sum(1 for r in rids if self.reports[r].status in
                      [ReportStatus.VALID, ReportStatus.PAID])
        invalid = sum(1 for r in rids if self.reports[r].status ==
                      ReportStatus.INVALID)
        dups    = sum(1 for r in rids if self.reports[r].status ==
                      ReportStatus.DUPLICATE)
        paid    = sum(self.reports[r].payout for r in rids
                      if self.reports[r].status == ReportStatus.PAID)
        return {
            "program_id":    program_id,
            "total_reports": len(rids),
            "valid":         valid,
            "invalid":       invalid,
            "duplicates":    dups,
            "total_paid":    paid,
            "escrow_bal":    p.escrow_bal,
        }

    # ════════════════════════════════════════════════════════
    #  ADMIN
    # ════════════════════════════════════════════════════════

    @gl.public.write
    def set_fee(self, bps: u256) -> bool:
        assert gl.message.sender == self.owner, "Only owner"
        assert bps <= 1000, "Max 10%"
        self.fee_bps = bps
        return True

    @gl.public.write
    def transfer_ownership(self, new_owner: Address) -> bool:
        assert gl.message.sender == self.owner, "Only owner"
        self.owner = new_owner
        return True

    # ════════════════════════════════════════════════════════
    #  INTERNAL HELPERS
    # ════════════════════════════════════════════════════════

    def _get_program(self, pid: str) -> Program:
        assert pid in self.programs, "Program not found"
        return self.programs[pid]

    def _get_report(self, rid: str) -> Report:
        assert rid in self.reports, "Report not found"
        return self.reports[rid]

    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def _calc_payout(self, program_id: str, severity: str) -> u256:
        p = self._get_program(program_id)
        reward_map = p.rewards
        return int(reward_map.get(severity, 0))

    def _get_program_report_summaries(
        self, program_id: str, exclude_id: str
    ) -> str:
        """Build compact summary of existing valid reports for AI dedup check"""
        rids   = self.program_reports.get(program_id, [])
        lines  = []
        for rid in rids:
            if rid == exclude_id:
                continue
            r = self.reports.get(rid)
            if r and r.status in [ReportStatus.VALID, ReportStatus.PAID]:
                lines.append(
                    f"[{rid}] {r.title} | severity: {r.ai_severity or r.severity}"
                )
        return "\n".join(lines) if lines else "None"
```

---

## Agent Interaction Flow

```
Sponsor                  Hunter                 GenLayer / AI
  │                        │                        │
  ├─ create_program() ───► │                        │
  ├─ fund_program()  ───► │                        │
  │                        │                        │
  │                        ├─ submit_report() ─────►│
  │                        │                        ├─ exec_prompt() [LLM triage]
  │                        │                        ├─ scope check
  │                        │                        ├─ dup detection
  │                        │                        ├─ severity scoring
  │                        │                        │
  │                        │◄──────── VALID + auto-pay ──────────┤
  │                        │◄──────── INVALID/DUPLICATE ─────────┤
  │                        │                        │
  ├─ (optional) raise_dispute() ───────────────────►│
  │                        │                        │
  ├─ resolve_dispute() ───────────────────────────► │
  │                        │◄──── outcome + payout ─┤
```

---

## Deployment

```bash
# Install GenLayer CLI
pip install genlayer

# Deploy to testnet
genlayer deploy contracts/BugBountyX.py --network testnet

# Seed a program (scripts/seed.py)
python scripts/seed.py \
  --contract <deployed_address> \
  --name "BugBountyX Alpha" \
  --rewards '{"critical":"1000000000000000000","high":"500000000000000000","medium":"100000000000000000","low":"50000000000000000","info":"0"}'
```

---

## Reward Tiers (Example Config)

| Severity | Example Payout |
|---|---|
| Critical | 1.0 ETH |
| High | 0.5 ETH |
| Medium | 0.1 ETH |
| Low | 0.05 ETH |
| Info | 0 |

Platform fee: **2% of payout** (configurable, max 10%)

---

## Key Design Decisions

**Why single contract?**
GenLayer charges per LLM call — keeping everything in one contract minimizes overhead and lets agent roles be method groups, not deployed addresses.

**Why `exec_prompt` only in validator?**
Non-determinism in GenLayer is expensive and requires validator consensus. All other logic is deterministic (pure state mutations).

**Duplicate detection**
The AI gets a compact summary of existing valid reports — title + severity — to check semantic similarity without blowing context limits.

**Dispute flow**
Disputes freeze the report status and escalate to platform owner as arbitrator. Production upgrade: replace owner with a multi-sig or DAO.

---

## Next Steps

- [ ] Add `re-validate` endpoint (re-runs AI triage on disputed reports)
- [ ] Multi-sig escrow release for high-value payouts
- [ ] Hunter reputation score (on-chain, updated per resolution)
- [ ] Frontend: React + viem + GenLayer SDK
- [ ] Integration with ArcPass for hunter identity / credential gating
