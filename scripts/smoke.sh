#!/usr/bin/env bash
# BugBountyX runtime smoke sequence.
#
#   scripts/smoke.sh            read-only: all 6 view methods
#   scripts/smoke.sh --write    program + escrow + report + triage + dispute, then all views
#   scripts/smoke.sh --help     show this help
#
# Write mode spends network fees and runs real consensus on triage_report.
# Configure and unlock the account first; never put a private key in this script.
set -euo pipefail

BUGBOUNTYX_CONTRACT="${BUGBOUNTYX_CONTRACT:-}"
PROGRAM_ID="${PROGRAM_ID:-1}"
REPORT_ID="${REPORT_ID:-${RID:-1}}"
DISPUTE_ID="${DISPUTE_ID:-}"
RETRIES="${RETRIES:-60}"
INTERVAL="${INTERVAL:-3000}"
TRIAGE_RETRIES="${TRIAGE_RETRIES:-180}"
FUND_VALUE="${FUND_VALUE:-2000000000000000000}"
SMOKE_ACCOUNT="${SMOKE_ACCOUNT:-rabby}"
ARBITRATE="${ARBITRATE:-0}"
MODE="${1:-read}"

PROGRAM_NAME="Smoke Vault Bounty"
PROGRAM_SCOPE="Vault and staking contracts of the target protocol. In scope: withdraw, deposit, share accounting, and reentrancy across those paths. Out of scope: off-chain infrastructure, third-party oracle failure, and gas-cost griefing without direct fund loss."
REPORT_TITLE="Reentrancy in Vault.withdraw drains pooled funds"
REPORT_DESC="Vault.withdraw sends GEN to msg.sender before decrementing shares, so the recipient callback can reenter withdraw with shares already counted as burned. An attacker can drain the pooled balance of the vault in a single transaction."
REPORT_POC="1. attacker deposits 1 GEN and receives 1 share. 2. attacker calls withdraw(1). 3. the transfer to the attacker triggers a fallback that calls withdraw(1) again before shares are decremented. 4. repeat until the pooled balance is drained."
REPORT_IMPACT="Full loss of pooled vault funds in one transaction; no user interaction required."
REPORT_SEVERITY="high"
DISPUTE_REASON="Smoke-path dispute raised to exercise the arbitration freeze; severity looks understated."

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
umask 077

WRITE_COUNT=0
READS_PASSED=0
READS_FAILED=0
LAST_TX_HASH=""
LAST_RESULT=""

usage() {
  printf '%s\n' \
    "Usage:" \
    "  scripts/smoke.sh                 read-only: all 6 view methods" \
    "  scripts/smoke.sh --write         full lifecycle, then all views" \
    "  scripts/smoke.sh --help          show this help" \
    "" \
    "Environment:" \
    "  BUGBOUNTYX_CONTRACT  deployed contract address (required)" \
    "  PROGRAM_ID          program to read in read mode (default: 1)" \
    "  REPORT_ID           report to read in read mode (default: 1)" \
    "  DISPUTE_ID          dispute to read in read mode; write mode sets it from" \
    "                       raise_dispute. No view enumerates dispute ids." \
    "  FUND_VALUE          GEN wei sent to fund_program (default: 2 GEN)" \
    "  RETRIES             receipt polling attempts (default: 60)" \
    "  INTERVAL            receipt polling interval in milliseconds (default: 3000)" \
    "  TRIAGE_RETRIES      receipt attempts for consensus methods (default: 180)" \
    "  SMOKE_ACCOUNT       active unlocked account name (default: rabby)" \
    "  ARBITRATE           1 to also resolve the dispute; requires the owner account" \
    "" \
    "Write mode creates a program, funds it, submits a report, runs real consensus" \
    "on triage_report, then exercises the dispute path. It spends network fees."
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v genlayer >/dev/null 2>&1 || fail "genlayer is required"
}

require_id() {
  local name="$1"
  local value="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || fail "$name must be a non-negative integer, got: $value"
}

extract_tx_hash() {
  awk '
    /Write Transaction Hash:/ {
      if (match($0, /0x[0-9a-fA-F]{64}/)) {
        print substr($0, RSTART, RLENGTH)
        exit
      }
      if (getline > 0 && match($0, /0x[0-9a-fA-F]{64}/)) {
        print substr($0, RSTART, RLENGTH)
        exit
      }
    }
  ' "$1"
}

extract_return() {
  awk '
    /result: \{ status: ['"'"']return['"'"']/ {
      if (match($0, /readable: ['"'"'][^'"'"']*['"'"']/)) {
        print substr($0, RSTART + 11, RLENGTH - 12)
        exit
      }
    }
  ' "$1"
}

wait_finalized() {
  local tx_hash="$1"
  local receipt_file="$2"
  local retries="${3:-$RETRIES}"

  if ! genlayer receipt "$tx_hash" --status FINALIZED --retries "$retries" --interval "$INTERVAL" >"$receipt_file" 2>&1; then
    printf 'finalization failed for %s\n' "$tx_hash" >&2
    return 1
  fi
  if ! grep -q "status_name: 'FINALIZED'" "$receipt_file"; then
    printf 'transaction did not finalize: %s\n' "$tx_hash" >&2
    return 1
  fi
  if ! grep -q "execution_result: 'SUCCESS'" "$receipt_file"; then
    printf 'transaction execution was not successful: %s\n' "$tx_hash" >&2
    printf 'see %s for the revert reason\n' "$receipt_file" >&2
    return 1
  fi
}

write_and_wait() {
  local retries="$RETRIES"
  if [[ "${1:-}" == "--retries" ]]; then
    retries="$2"
    shift 2
  fi
  local method="$1"
  shift
  local write_file="$TMP_DIR/write-$WRITE_COUNT.log"
  local receipt_file="$TMP_DIR/receipt-$WRITE_COUNT.log"
  local tx_hash

  WRITE_COUNT=$((WRITE_COUNT + 1))
  printf 'write: %s\n' "$method"
  if ! genlayer write "$BUGBOUNTYX_CONTRACT" "$method" "$@" >"$write_file" 2>&1; then
    printf 'write failed: %s\n' "$method" >&2
    awk 'NR <= 20 { print }' "$write_file" >&2
    return 1
  fi

  tx_hash="$(extract_tx_hash "$write_file")"
  [[ "$tx_hash" =~ ^0x[0-9a-fA-F]{64}$ ]] || {
    printf 'could not determine transaction hash for %s\n' "$method" >&2
    return 1
  }
  printf '  transaction: %s\n' "$tx_hash"
  wait_finalized "$tx_hash" "$receipt_file" "$retries"

  LAST_TX_HASH="$tx_hash"
  LAST_RESULT="$(extract_return "$receipt_file")"
  if [[ -n "$LAST_RESULT" ]]; then
    printf '  return: %s\n' "$LAST_RESULT"
  fi
}

require_returned_id() {
  local method="$1"
  [[ "$LAST_RESULT" =~ ^[0-9]+$ ]] || fail "$method did not return a usable numeric ID"
}

call_method() {
  local method="$1"
  shift
  genlayer call "$BUGBOUNTYX_CONTRACT" "$method" "$@"
}

run_read() {
  local method="$1"
  shift
  printf 'read: %s\n' "$method"
  if call_method "$method" "$@"; then
    READS_PASSED=$((READS_PASSED + 1))
  else
    printf '  read failed: %s\n' "$method" >&2
    READS_FAILED=$((READS_FAILED + 1))
  fi
}

run_write_lifecycle() {
  # 1. deterministic: open a program. Rewards must descend critical>=high>=medium>=low.
  write_and_wait create_program \
    --args "$PROGRAM_NAME" "$PROGRAM_SCOPE" 1000 500 100 50
  PROGRAM_ID="$LAST_RESULT"
  require_returned_id create_program
  require_id PROGRAM_ID "$PROGRAM_ID"
  printf '  program: %s\n' "$PROGRAM_ID"

  # 2. deterministic + payable: escrow the GEN the program is willing to lose.
  write_and_wait fund_program --args "$PROGRAM_ID" --value "$FUND_VALUE"
  printf '  escrowed: %s wei\n' "$FUND_VALUE"

  # 3. deterministic: intake. No LLM, so a sponsor cannot refuse to accept work.
  write_and_wait submit_report \
    --args "$PROGRAM_ID" "$REPORT_TITLE" "$REPORT_DESC" \
    "$REPORT_POC" "$REPORT_IMPACT" "$REPORT_SEVERITY"
  REPORT_ID="$LAST_RESULT"
  require_returned_id submit_report
  require_id REPORT_ID "$REPORT_ID"

  # 4. the only consensus method. Longer polling: validators must re-run the prompt.
  write_and_wait --retries "$TRIAGE_RETRIES" triage_report --args "$REPORT_ID"
  printf '  triage transaction (consensus evidence): %s\n' "$LAST_TX_HASH"

  # 5. dispute path: freezes the report so no payout can run during arbitration.
  write_and_wait raise_dispute --args "$REPORT_ID" "$DISPUTE_REASON"
  DISPUTE_ID="$LAST_RESULT"
  require_returned_id raise_dispute
  require_id DISPUTE_ID "$DISPUTE_ID"
  printf '  dispute: %s\n' "$DISPUTE_ID"

  # 6. requeue back to pending for a fresh consensus round (sponsor-authorized).
  write_and_wait requeue_disputed --args "$REPORT_ID"

  # 7. optional: owner arbitration. Only valid when the smoke account is the owner.
  if [[ "$ARBITRATE" == "1" ]]; then
    write_and_wait resolve_dispute --args "$DISPUTE_ID" valid medium
  else
    printf 'skip: resolve_dispute (set ARBITRATE=1 with the owner account)\n'
  fi
}

run_reads() {
  require_id PROGRAM_ID "$PROGRAM_ID"
  require_id REPORT_ID "$REPORT_ID"

  run_read get_program --args "$PROGRAM_ID"
  run_read get_report --args "$REPORT_ID"
  run_read get_program_reports --args "$PROGRAM_ID" 0 20
  run_read get_pending_queue --args 10
  run_read get_program_stats --args "$PROGRAM_ID"

  if [[ -n "$DISPUTE_ID" ]]; then
    run_read get_dispute --args "$DISPUTE_ID"
  fi

  printf '\nreads passed: %d, failed: %d\n' "$READS_PASSED" "$READS_FAILED"
  [[ "$READS_FAILED" -eq 0 ]] || return 1
}

case "$MODE" in
  --help|-h)
    usage
    exit 0
    ;;
  read|--read)
    require_command
    [[ -n "$BUGBOUNTYX_CONTRACT" ]] || fail "set BUGBOUNTYX_CONTRACT to a deployed address"
    printf 'target: %s\n' "$BUGBOUNTYX_CONTRACT"
    run_reads
    ;;
  --write)
    require_command
    [[ -n "$BUGBOUNTYX_CONTRACT" ]] || fail "set BUGBOUNTYX_CONTRACT to a deployed address"
    [[ "$BUGBOUNTYX_CONTRACT" =~ ^0x[0-9a-fA-F]{40}$ ]] || fail "BUGBOUNTYX_CONTRACT is not a valid address"
    require_id RETRIES "$RETRIES"
    require_id INTERVAL "$INTERVAL"
    require_id TRIAGE_RETRIES "$TRIAGE_RETRIES"
    [[ "$FUND_VALUE" =~ ^[0-9]+$ ]] || fail "FUND_VALUE must be an integer amount of wei"
    [[ "$FUND_VALUE" -gt 0 ]] || fail "FUND_VALUE must be greater than zero"
    network_output="$(genlayer config get network 2>&1)" || fail "could not read the GenLayer network"
    network="$(awk -F= '/^network=/{print $2; exit}' <<< "$network_output")"
    case "$network" in
      studionet|testnet-bradbury|testnet-asimov|testnet_bradbury|testnet_asimov) ;;
      *) fail "write mode requires a real test network, found: ${network:-unknown}" ;;
    esac
    account_output="$(genlayer account show 2>&1)" || fail "could not read the active GenLayer account"
    [[ "$account_output" == *"name: '$SMOKE_ACCOUNT'"* ]] || fail "active account must be $SMOKE_ACCOUNT"
    [[ "$account_output" == *"status: 'unlocked'"* ]] || fail "$SMOKE_ACCOUNT must be unlocked"
    [[ "$account_output" == *"active: true"* ]] || fail "$SMOKE_ACCOUNT must be the active account"
    printf 'target: %s\n' "$BUGBOUNTYX_CONTRACT"
    printf 'network: %s\n' "$network"
    printf 'wallet: %s is active and unlocked; writes will spend network fees\n' "$SMOKE_ACCOUNT"
    printf 'note: the same account sponsors, submits, and disputes, so the dispute check passes\n'
    run_write_lifecycle
    run_reads
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
