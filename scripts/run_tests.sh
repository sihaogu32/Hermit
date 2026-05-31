#!/usr/bin/env bash
# run_tests.sh — 跑 hermit 自製擴充的測試（tool 層 + plugin 層）。
#
# 測試清單由 manifest 衍生（不硬編、不會漂移）：
#   - tool 層：patches/hermes-agent/manifest.sh 的 HA_FILES 內 tests/.../test_*.py
#   - plugin 層：.hermes-overlay/manifest.sh 的 HERMES_OVERLAY_PATHS 內 plugins/*/tests/test_*.py
# 兩層都從「runtime layout」（$HERMES_HOME/hermes-agent 為 cwd）執行——
# 因 plugin 測試以 parents[3]/hermes-agent 推算 core 位置，必須在組裝好的 HERMES_HOME 下跑。
#
# 前置：$HERMES_HOME/hermes-agent 已存在，且 overlay/patches 已 import 進去
#   （本機＝真實 runtime；CI＝先 clone 上游再跑 scripts/sync_overlays.sh import）。
#
# 用法：
#   scripts/run_tests.sh                 # 用 $HERMES_HOME/hermes-agent/venv/bin/python（runtime）
#   PYTEST_PYTHON=$(command -v python) scripts/run_tests.sh    # 指定直譯器（CI）
#   scripts/run_tests.sh -q -x           # 多餘參數原樣轉給 pytest
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HA_DIR="$HERMES_HOME/hermes-agent"

[[ -d "$HA_DIR" ]] || { echo "[run_tests] 找不到 $HA_DIR（請先 install runtime，或 CI 先 clone+import）" >&2; exit 1; }

# 直譯器：環境指定 > runtime venv > system python3
PYTEST_PYTHON="${PYTEST_PYTHON:-$HA_DIR/venv/bin/python}"
[[ -x "$PYTEST_PYTHON" ]] || PYTEST_PYTHON="$(command -v python3)"

# shellcheck source=../patches/hermes-agent/manifest.sh
source "$REPO_ROOT/patches/hermes-agent/manifest.sh"   # → HA_FILES
# shellcheck source=../.hermes-overlay/manifest.sh
source "$REPO_ROOT/.hermes-overlay/manifest.sh"        # → HERMES_OVERLAY_PATHS

tool_tests=()
for rel in "${HA_FILES[@]}"; do
  case "$rel" in tests/*) [[ "$(basename "$rel")" == test_*.py ]] && tool_tests+=("$rel") ;; esac
done
plugin_tests=()
for rel in "${HERMES_OVERLAY_PATHS[@]}"; do
  case "$rel" in plugins/*/tests/*) [[ "$(basename "$rel")" == test_*.py ]] && plugin_tests+=("$HERMES_HOME/$rel") ;; esac
done

# -o 'addopts=' 清掉上游 hermes 預設的 pytest addopts（否則會撈整個 tests/ 樹）
PYTEST=( "$PYTEST_PYTHON" -m pytest -o "addopts=" "$@" )
rc=0

echo "== tool 層（${#tool_tests[@]} 檔）=="
( cd "$HA_DIR" && "${PYTEST[@]}" "${tool_tests[@]}" ) || rc=1

echo "== plugin 層（${#plugin_tests[@]} 檔）=="
( cd "$HA_DIR" && "${PYTEST[@]}" "${plugin_tests[@]}" ) || rc=1

[[ $rc -eq 0 ]] && echo "[run_tests] 全數通過。" || echo "[run_tests] 有測試失敗（見上）。" >&2
exit $rc
