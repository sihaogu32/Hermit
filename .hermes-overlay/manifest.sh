# .hermes/ 擴充點白名單
# 由 scripts/sync_overlays.sh source；路徑相對 .hermes/ 與 .hermes-overlay/
# 支援 shell glob（例如 plugins/*）— rsync 時會展開
HERMES_OVERLAY_PATHS=(
  "SOUL.md"
  "config.yaml"
  "memories/MEMORY.md"
  "memories/USER.md"
  "skills/*"
  "plugins/*"
)
