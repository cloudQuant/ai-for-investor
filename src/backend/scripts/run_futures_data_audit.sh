#!/usr/bin/env bash
# Run the futures daily-data audits in order.
#
# Usage:
#   ./scripts/run_futures_data_audit.sh daily    # trading days + contracts
#   ./scripts/run_futures_data_audit.sh weekly   # all three, including per-contract bars
#   ./scripts/run_futures_data_audit.sh bars --no-repair
#
# Common options (--as-of, --no-repair, --max-repair-days, ...) are forwarded
# to every script. Script-specific options are forwarded only to the matching
# script in daily/weekly mode.
#
# Suggested cron entries (run after the daily market-data sync):
#   30 20 * * 1-5  cd /path/to/ai-for-investor/src/backend && ./scripts/run_futures_data_audit.sh daily  >> logs/futures_data_audit/cron.log 2>&1
#   0  9 * * 6     cd /path/to/ai-for-investor/src/backend && ./scripts/run_futures_data_audit.sh weekly >> logs/futures_data_audit/cron.log 2>&1

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

export PYTHONPATH="$BACKEND_DIR${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$BACKEND_DIR/logs/futures_data_audit"

mode="${1:-daily}"
if [ "$#" -gt 0 ]; then
  shift
fi

status=0
FILTERED=()

run() {
  echo "==> $(date '+%Y-%m-%d %H:%M:%S') $*"
  python3 "$@"
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "$status" -eq 0 ]; then
    status="$rc"
  fi
}

filter_args() {
  local script="$1"
  shift
  FILTERED=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --as-of|--markets|--start-date|--max-repair-days|--chunk-days|--sleep-seconds|--report-dir)
        FILTERED+=("$1" "${2:-}")
        shift 2
        ;;
      --no-repair|-v|--verbose)
        FILTERED+=("$1")
        shift
        ;;
      --no-refresh-calendar|--retry-unavailable|--no-refresh-reference|--refresh-reference-days|--max-repair-contracts|--symbols|--min-missing-days)
        case "$script" in
          trading-days)
            case "$1" in
              --no-refresh-calendar|--retry-unavailable) FILTERED+=("$1") ;;
              *) echo "warning: $1 is not used by trading-days; ignored" >&2 ;;
            esac
            ;;
          contracts)
            case "$1" in
              --no-refresh-reference|--refresh-reference-days|--max-repair-contracts)
                if [ "$1" = "--no-refresh-reference" ]; then
                  FILTERED+=("$1")
                else
                  FILTERED+=("$1" "${2:-}")
                  shift
                fi
                ;;
              *) echo "warning: $1 is not used by contracts; ignored" >&2 ;;
            esac
            ;;
          bars)
            case "$1" in
              --retry-unavailable)
                FILTERED+=("$1")
                ;;
              --symbols|--min-missing-days)
                FILTERED+=("$1" "${2:-}")
                shift
                ;;
              *) echo "warning: $1 is not used by bars; ignored" >&2 ;;
            esac
            ;;
        esac
        shift
        ;;
      *)
        echo "warning: unsupported option $1; ignored" >&2
        shift
        ;;
    esac
  done
}

run_filtered() {
  local script="$1"
  local module="$2"
  shift 2
  filter_args "$script" "$@"
  run "scripts/${module}" "${FILTERED[@]}"
}

case "$mode" in
  daily)
    run_filtered trading-days audit_futures_daily_trading_days.py "$@"
    run_filtered contracts audit_futures_daily_contracts.py "$@"
    ;;
  weekly)
    run_filtered trading-days audit_futures_daily_trading_days.py "$@"
    run_filtered contracts audit_futures_daily_contracts.py "$@"
    run_filtered bars audit_futures_daily_bars.py "$@"
    ;;
  trading-days)
    run scripts/audit_futures_daily_trading_days.py "$@"
    ;;
  contracts)
    run scripts/audit_futures_daily_contracts.py "$@"
    ;;
  bars)
    run scripts/audit_futures_daily_bars.py "$@"
    ;;
  *)
    echo "Usage: $0 {daily|weekly|trading-days|contracts|bars} [options]" >&2
    exit 2
    ;;
esac

exit "$status"
