#!/usr/bin/env bash
###############################################################################
# entrypoint.sh — hermit 個人化 AI agent 容器啟動腳本（巢狀版面）
#
# 用法（第一個參數即 hermes 子命令）：
#   docker run ... hermit            # 預設 → hermes web（9119 管理後台）
#   docker run ... hermit run        # gateway（8642 OpenAI 相容 chat）
#   docker run -it ... hermit cli    # 互動 CLI
#   docker run ... hermit doctor     # 任意 hermes 子命令直接透傳
###############################################################################
set -euo pipefail

export HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
HERMES_BIN="${HERMES_HOME}/hermes-agent/venv/bin/hermes"

# ── C：secrets 一律 runtime 提供，image 內不含 ────────────────────────────
# 期望 (擇一)：
#   1) -v /your/secrets/.env:/root/.hermes/.env:ro
#   2) -e OPENAI_API_KEY=... / -e ANTHROPIC_API_KEY=... / -e OPENROUTER_API_KEY=...
if [[ ! -f "${HERMES_HOME}/.env" ]] \
   && [[ -z "${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${OPENROUTER_API_KEY:-}${HERMES_API_KEY:-}" ]]; then
  echo "[entrypoint] ⚠ 未偵測到 ${HERMES_HOME}/.env，也沒有任何 *_API_KEY 環境變數。" >&2
  echo "[entrypoint]   agent 將無法呼叫模型——請 -v 掛 ~/.hermes/.env 或 -e 帶入憑證。" >&2
fi

# 'cli' 當互動模式別名（等同直接跑 hermes）
cmd="${1:-web}"
if [[ "$cmd" == "cli" ]]; then shift; exec "${HERMES_BIN}" "$@"; fi

# 注意：hermes web/run 預設 bind 127.0.0.1；要從 host 連請看 HTML 指南「對外暴露」一節。
exec "${HERMES_BIN}" "${@:-web}"
