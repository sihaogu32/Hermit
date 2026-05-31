# .hermes/ 擴充點白名單
# 由 scripts/sync_overlays.sh source；路徑相對 .hermes/ 與 .hermes-overlay/
#
# 原則：overlay 是「我的擴充（delta vs stock hermes）」的選擇性鏡像，**不鏡像上游 stock 資產**。
# 因此 skill / plugin 要逐一列出我自己加的，不要用 `skills/*`、`plugins/*` blanket glob
# ——blanket glob 會把上游 ~90 個 bundled skill 全掃進來（違反原則、且會踩到 stock skill 內的 secret placeholder）。
# 路徑支援 shell glob，但僅用於精準匹配單一擴充（rsync 時展開）。
HERMES_OVERLAY_PATHS=(
  "SOUL.md"
  "config.yaml"
  "memories/MEMORY.md"
  "memories/USER.md"
  # 我自己的客製 skill / plugin（有了才逐一加；勿用 skills/* plugins/* blanket glob）。
  # 例：
  #   "skills/personal/<my_skill>"
  #   "plugins/<my_connector>"
  "plugins/consent-center/dashboard/manifest.json"
  "plugins/consent-center/dashboard/plugin_api.py"
  "plugins/consent-center/dashboard/dist/index-0.1.0.js"
  "plugins/consent-center/tests/test_consent_center_api.py"
  "plugins/consent-center/tests/sample_proposal.json"
  "plugins/calendar/dashboard/manifest.json"
  "plugins/calendar/dashboard/plugin_api.py"
  "plugins/calendar/dashboard/dist/index-0.1.0.js"
  "plugins/calendar/tests/test_calendar_api.py"
)
