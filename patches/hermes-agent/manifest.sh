# hermes-agent/ 內擴充白名單
# 由 scripts/sync_overlays.sh source；路徑相對 hermes-agent/
#
# 目前無自製檔。P1 起新增 connector 相關工具時，把新路徑加進來：
#   新增檔 → HA_FILES（鏡像到 patches/hermes-agent/files/）
#   修改既有上游檔 → HA_DIFFS（.patch 存到 patches/hermes-agent/diffs/）

HA_FILES=(
  "tools/consent_memory.py"
  "tools/consent_propose_tool.py"
)

HA_DIFFS=()
