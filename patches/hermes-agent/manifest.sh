# hermes-agent/ 內擴充白名單
# 由 scripts/sync_overlays.sh source；路徑相對 hermes-agent/
#
# 新增 connector 相關工具時，把新路徑加進來：
#   新增檔 → HA_FILES（鏡像到 patches/hermes-agent/files/）
#   修改既有上游檔 → HA_DIFFS（.patch 存到 patches/hermes-agent/diffs/）

HA_FILES=(
  "tools/consent_memory.py"
  "tools/consent_propose_tool.py"
  "tools/google_calendar.py"
  "tools/calendar_store.py"
  "tools/calendar_read.py"
  "tools/consent_event.py"
  "tests/tools/test_google_calendar.py"
  "tests/tools/test_calendar_store.py"
  "tests/tools/test_calendar_read.py"
  "tests/tools/test_consent_event.py"
  "tests/tools/test_consent_memory.py"
  "tests/tools/test_consent_propose_tool.py"
)

HA_DIFFS=()
