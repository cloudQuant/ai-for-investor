#!/bin/bash

###############################################################################
# ai-for-investor - 停止脚本
###############################################################################

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PID_DIR="$PROJECT_ROOT/.pids"

# PID 文件
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

echo -e "${CYAN}"
echo "======================================"
echo "  ai-for-investor - 停止项目"
echo "======================================"
echo -e "${NC}"

STOPPED_BACKEND=false
STOPPED_FRONTEND=false

stop_pid_file() {
    local label="$1"
    local pid_file="$2"
    local stopped_var="$3"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || true)
        echo -e "${BLUE}停止${label}服务...${NC}"
        if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
            kill "$pid" 2>/dev/null || true
            local waited=0
            while [ $waited -lt 5 ] && ps -p "$pid" > /dev/null 2>&1; do
                sleep 1
                waited=$((waited + 1))
            done
            if ps -p "$pid" > /dev/null 2>&1; then
                echo -e "  ${YELLOW}强制停止${label}服务...${NC}"
                kill -9 "$pid" 2>/dev/null || true
            fi
            echo -e "  ${GREEN}${label}服务已停止 (PID: $pid)${NC}"
            eval "$stopped_var=true"
        else
            echo -e "  ${YELLOW}${label}服务未运行 (PID: ${pid:-unknown})${NC}"
        fi
        rm -f "$pid_file"
    else
        echo -e "${YELLOW}${label} PID 文件不存在${NC}"
    fi
}

stop_pid_file "后端" "$BACKEND_PID_FILE" STOPPED_BACKEND
stop_pid_file "前端" "$FRONTEND_PID_FILE" STOPPED_FRONTEND

###############################################################################
# 清理可能残留的进程
###############################################################################

echo ""
echo -e "${BLUE}清理残留进程...${NC}"

# 查找并停止可能残留的 uvicorn 进程
REMAINING_BACKEND=$(ps aux | grep -v grep | grep "uvicorn app.main:app" | awk '{print $2}' || true)
if [ -n "$REMAINING_BACKEND" ]; then
    echo -e "  ${YELLOW}停止残留的后端进程...${NC}"
    echo "$REMAINING_BACKEND" | xargs kill -9 2>/dev/null || true
fi

# 查找并停止可能残留的 vite 进程
REMAINING_FRONTEND=$(ps aux | grep -v grep | grep -E "vite.*(ai-for-investor|backtrader)" | awk '{print $2}' || true)
if [ -n "$REMAINING_FRONTEND" ]; then
    echo -e "  ${YELLOW}停止残留的前端进程...${NC}"
    echo "$REMAINING_FRONTEND" | xargs kill -9 2>/dev/null || true
fi

# 仅终止监听端口的服务端进程，避免误杀浏览器或客户端连接
for port in 8000 3000; do
    OCCUPIED=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$OCCUPIED" ]; then
        echo -e "  ${YELLOW}停止监听端口 ${port} 的进程...${NC}"
        echo "$OCCUPIED" | xargs kill -9 2>/dev/null || true
    fi
done

###############################################################################
# 完成
###############################################################################

echo ""
if [ "$STOPPED_BACKEND" = true ] || [ "$STOPPED_FRONTEND" = true ]; then
    echo -e "${GREEN}======================================"
    echo "  服务已停止"
    echo -e "======================================${NC}"
else
    echo -e "${YELLOW}======================================"
    echo "  没有运行中的服务"
    echo -e "======================================${NC}"
fi
echo ""
echo -e "  ${CYAN}启动服务:${NC} ./scripts/start_app.sh"
echo ""
