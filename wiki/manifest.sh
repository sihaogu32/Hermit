# wiki/ 鏡像設定
# 由 scripts/sync_overlays.sh source。
#
# wiki/ 是 hermes 自帶 /llm-wiki 的整目錄鏡像：runtime 在 config `wiki.path`（預設 ~/wiki，
# host = /home/laura/wiki、Docker = /root/wiki），repo 只保存其 git 鏡像。
# 與 .hermes-overlay（白名單挑檔）不同，wiki 是「整目錄鏡像、用排除清單剔除不入 git 的東西」。
#
# 下列項目於 export/import 時都排除：
#   - mirror-only 檔（manifest.sh / .gitkeep）— 它們只存在於 repo 鏡像，不可被 --delete 清掉、也不該回灌 runtime
#   - cache / 暫存 / 編譯產物
WIKI_RSYNC_EXCLUDES=(
  "manifest.sh"
  ".gitkeep"
  "personal/cache"
  "__pycache__"
  "*.pyc"
  ".DS_Store"
  "*.swp"
  "*.tmp"
)
