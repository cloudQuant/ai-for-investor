#!/bin/bash
set -e

cd "$(dirname "$0")"

PID_DIR="$HOME/.ai-for-investor"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

get_pid_from_port() {
    lsof -ti :$1 2>/dev/null | head -1
}

log "========================================="
log "   ai-for-investor Service Status"
log "========================================="
echo ""

status_service() {
    local name=$1
    local port=$2
    local pid_file="$PID_DIR/$name.pid"
    local pid=""

    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
    fi

    if check_port $port; then
        local actual_pid=$(get_pid_from_port $port)
        if [ -n "$actual_pid" ]; then
            if [ "$pid" = "$actual_pid" ]; then
                log "✓ $name is RUNNING (PID: $pid, Port: $port)"
            else
                log "✓ $name is RUNNING (PID: $actual_pid, Port: $port) [PID file: $pid]"
                pid=$actual_pid
            fi

            if [ -f "$PID_DIR/$name.log" ]; then
                local last_lines=$(tail -3 "$PID_DIR/$name.log" 2>/dev/null | sed 's/^/  /')
                if [ -n "$last_lines" ]; then
                    echo "  Recent log:"
                    echo "$last_lines"
                fi
            fi
        else
            log "✗ $name port is open but process not found"
        fi
    else
        log "✗ $name is NOT RUNNING (Port: $port)"
        if [ -f "$pid_file" ]; then
            log "  (Stale PID file: $pid)"
        fi
    fi
}

echo "Backend Service:"
status_service "backend" 8000
echo ""
echo "Frontend Service:"
status_service "frontend" 3000
echo ""
log "========================================="
log "Logs: $PID_DIR/"
ls -la "$PID_DIR" 2>/dev/null | grep -v '^total' | sed 's/^/  /' || log "  No log files found"
