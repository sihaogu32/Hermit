#!/usr/bin/env bash
# sync_overlays.sh — 在 .hermes/ + hermes-agent/ 與其受 git 追蹤的鏡像之間雙向同步
#
# 用法：
#   scripts/sync_overlays.sh export   # 由實況推到鏡像（commit 前用）
#   scripts/sync_overlays.sh import   # 由鏡像推回實況（還原時用）
#
# 詳細策略見 docs/backup-strategy.md
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 真實 runtime 在 HERMES_HOME（上游預設 ~/.hermes），不在本 repo 內。
# 本 repo 只保存鏡像（.hermes-overlay/、patches/hermes-agent/），由本腳本與真實 runtime 雙向同步。
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_DIR="$HERMES_HOME"
HERMES_OVERLAY="$REPO_ROOT/.hermes-overlay"
HA_DIR="$HERMES_HOME/hermes-agent"
PATCHES_DIR="$REPO_ROOT/patches/hermes-agent"
PATCHES_FILES="$PATCHES_DIR/files"
PATCHES_DIFFS="$PATCHES_DIR/diffs"
# hermes /llm-wiki：runtime 在 config wiki.path（預設 ~/wiki，不在 HERMES_HOME 內），repo 整目錄鏡像。
WIKI_DIR="${HERMES_WIKI_DIR:-$HOME/wiki}"
WIKI_MIRROR="$REPO_ROOT/wiki"

# shellcheck source=../.hermes-overlay/manifest.sh
source "$HERMES_OVERLAY/manifest.sh"
# shellcheck source=../patches/hermes-agent/manifest.sh
source "$PATCHES_DIR/manifest.sh"
# shellcheck source=../wiki/manifest.sh
source "$WIKI_MIRROR/manifest.sh"

log() { printf '[sync_overlays] %s\n' "$*" >&2; }
warn() { printf '[sync_overlays] WARN: %s\n' "$*" >&2; }
die() { printf '[sync_overlays] ABORT: %s\n' "$*" >&2; exit 1; }

# Secrets pattern：行尾若是空字串（''/""）視為安全；其他非空一律視為命中
check_secrets_in_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local hits
  hits=$(grep -nE "^[[:space:]]*(api_key|secret|password|token|client_secret|access_token|refresh_token):" "$file" \
    | grep -vE ":[[:space:]]*(''|\"\")[[:space:]]*$" \
    | grep -vE ":[[:space:]]*$" || true)
  if [[ -n "$hits" ]]; then
    printf '  在 %s 命中：\n%s\n' "$file" "$hits" >&2
    return 1
  fi
  return 0
}

run_secrets_audit() {
  log "Secrets 兜底掃描..."
  local failed=0
  local roots=( "$HERMES_OVERLAY" )
  [[ -d "$WIKI_MIRROR" ]] && roots+=( "$WIKI_MIRROR" )
  while IFS= read -r -d '' f; do
    if ! check_secrets_in_file "$f"; then
      failed=1
    fi
  done < <(find "${roots[@]}" -type f \( -name "*.yaml" -o -name "*.yml" -o -name "*.md" -o -name "*.json" -o -name "*.env" -o -name "*.toml" \) -print0)
  [[ $failed -eq 0 ]] || die "偵測到非空 secret 欄位；請清空後再 export，或檢查白名單是否誤納敏感檔。"
  log "Secrets 掃描通過。"
}

do_export() {
  [[ -d "$HERMES_DIR" ]] || die "HERMES_HOME 不存在於 $HERMES_DIR（預設 ~/.hermes；請先 install hermes）"
  [[ -d "$HA_DIR" ]] || die "hermes-agent/ 不存在於 $HA_DIR（應為 \$HERMES_HOME/hermes-agent）"

  log "===== EXPORT: .hermes/ → .hermes-overlay/ ====="
  for pattern in "${HERMES_OVERLAY_PATHS[@]}"; do
    # shellcheck disable=SC2206
    local matches=( $HERMES_DIR/$pattern )
    if [[ ! -e "${matches[0]}" ]]; then
      # glob 無實況時 silent，固定路徑無實況才 warn
      [[ "$pattern" == *[*?]* ]] || warn "白名單路徑無實況：$pattern（跳過）"
      continue
    fi
    for src in "${matches[@]}"; do
      [[ -e "$src" ]] || continue
      local rel="${src#"$HERMES_DIR/"}"
      local dst="$HERMES_OVERLAY/$rel"
      mkdir -p "$(dirname "$dst")"
      if [[ -d "$src" ]]; then
        rsync -a --delete \
          --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
          --exclude='.DS_Store' --exclude='*.swp' --exclude='*.tmp' \
          "$src/" "$dst/"
      else
        rsync -a "$src" "$dst"
      fi
      log "  + $rel"
    done
  done

  log "===== EXPORT: hermes-agent/ → patches/hermes-agent/files ====="
  for rel in "${HA_FILES[@]}"; do
    local src="$HA_DIR/$rel"
    local dst="$PATCHES_FILES/$rel"
    if [[ ! -e "$src" ]]; then
      warn "白名單檔案不存在：$rel（跳過）"
      continue
    fi
    mkdir -p "$(dirname "$dst")"
    rsync -a "$src" "$dst"
    log "  + $rel"
  done

  log "===== EXPORT: hermes-agent/ → patches/hermes-agent/diffs ====="
  for rel in "${HA_DIFFS[@]}"; do
    local src="$HA_DIR/$rel"
    local dst="$PATCHES_DIFFS/$rel.patch"
    if [[ ! -e "$src" ]]; then
      warn "白名單檔案不存在：$rel（跳過）"
      continue
    fi
    mkdir -p "$(dirname "$dst")"
    # diff 對於 hermes-agent/ 內的 git tracked 檔產出標準 patch
    if ! git -C "$HA_DIR" diff -- "$rel" > "$dst.tmp"; then
      rm -f "$dst.tmp"
      die "git diff 失敗：$rel"
    fi
    if [[ ! -s "$dst.tmp" ]]; then
      warn "空 diff（無改動）：$rel — 移除 $dst.tmp 並刪舊 patch"
      rm -f "$dst.tmp" "$dst"
    else
      mv "$dst.tmp" "$dst"
      log "  + $rel.patch"
    fi
  done

  log "===== EXPORT: \$WIKI_DIR → wiki/ ====="
  if [[ -d "$WIKI_DIR" ]]; then
    local wex=() e
    for e in "${WIKI_RSYNC_EXCLUDES[@]}"; do wex+=( "--exclude=$e" ); done
    rsync -a --delete "${wex[@]}" "$WIKI_DIR/" "$WIKI_MIRROR/"
    log "  + wiki/（整目錄鏡像 $WIKI_DIR）"
  else
    warn "wiki 實況不存在：$WIKI_DIR（跳過；hermes /llm-wiki 尚未 init？）"
  fi

  log "===== EXPORT: 防呆檢查 ====="
  # untracked 但 manifest 未列入的 .py / .md（hermes-agent/ 內）
  local extras
  extras=$(git -C "$HA_DIR" ls-files --others --exclude-standard \
    | grep -E "\.(py|md)$" || true)
  if [[ -n "$extras" ]]; then
    while IFS= read -r f; do
      local known=0
      for k in "${HA_FILES[@]}" "${HA_DIFFS[@]}"; do
        [[ "$f" == "$k" ]] && { known=1; break; }
      done
      [[ $known -eq 0 ]] && warn "hermes-agent/ 內 untracked 但未列入 manifest：$f（如為擴充請加進 patches/hermes-agent/manifest.sh）"
    done <<< "$extras"
  fi

  run_secrets_audit
  log "EXPORT 完成。下一步：git status 確認變動，git add 並 commit。"
}

do_import() {
  [[ -d "$HERMES_OVERLAY" ]] || die ".hermes-overlay/ 不存在於 $HERMES_OVERLAY"
  [[ -d "$HA_DIR" ]] || die "hermes-agent/ 不存在於 $HA_DIR — 請先依 docs/install-runtime.md install hermes-agent。"
  mkdir -p "$HERMES_DIR"

  run_secrets_audit  # 還原前也掃一次，確保 git 上的鏡像沒被誤推 secret

  log "===== IMPORT: .hermes-overlay/ → .hermes/ ====="
  for pattern in "${HERMES_OVERLAY_PATHS[@]}"; do
    # shellcheck disable=SC2206
    local matches=( $HERMES_OVERLAY/$pattern )
    if [[ ! -e "${matches[0]}" ]]; then
      [[ "$pattern" == *[*?]* ]] || warn "鏡像中無 $pattern（可能未產出，跳過）"
      continue
    fi
    for src in "${matches[@]}"; do
      [[ -e "$src" ]] || continue
      local rel="${src#"$HERMES_OVERLAY/"}"
      local dst="$HERMES_DIR/$rel"
      mkdir -p "$(dirname "$dst")"
      if [[ -d "$src" ]]; then
        rsync -a \
          --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
          "$src/" "$dst/"
      else
        rsync -a "$src" "$dst"
      fi
      log "  + $rel"
    done
  done

  log "===== IMPORT: patches/hermes-agent/files → hermes-agent/ ====="
  for rel in "${HA_FILES[@]}"; do
    local src="$PATCHES_FILES/$rel"
    local dst="$HA_DIR/$rel"
    if [[ ! -e "$src" ]]; then
      warn "鏡像中無 $rel（跳過）"
      continue
    fi
    mkdir -p "$(dirname "$dst")"
    rsync -a "$src" "$dst"
    log "  + $rel"
  done

  log "===== IMPORT: patches/hermes-agent/diffs → hermes-agent/（git apply）====="
  local apply_failed=0
  for rel in "${HA_DIFFS[@]}"; do
    local patch="$PATCHES_DIFFS/$rel.patch"
    if [[ ! -e "$patch" ]]; then
      warn "鏡像中無 $rel.patch（跳過）"
      continue
    fi
    # 先以 --check 預演，不污染工作區
    if git -C "$HA_DIR" apply --check "$patch" 2>/dev/null; then
      git -C "$HA_DIR" apply "$patch"
      log "  + $rel.patch"
    else
      # 可能已套過 — 試試反向是否乾淨（代表完全套用過）
      if git -C "$HA_DIR" apply --reverse --check "$patch" 2>/dev/null; then
        log "  = $rel.patch（已套用，跳過）"
      else
        warn "套用 $rel.patch 失敗 — 可能 upstream 改了該檔；請手動 rebase patch。"
        apply_failed=1
      fi
    fi
  done

  if [[ $apply_failed -ne 0 ]]; then
    die "至少一個 patch 套用失敗，請見上方訊息。"
  fi

  log "===== IMPORT: wiki/ → \$WIKI_DIR ====="
  if [[ -d "$WIKI_MIRROR" ]]; then
    mkdir -p "$WIKI_DIR"
    local wex=() e
    for e in "${WIKI_RSYNC_EXCLUDES[@]}"; do wex+=( "--exclude=$e" ); done
    # import 不帶 --delete：不清掉 runtime 上比鏡像新的頁（與 overlay import 同策略）
    rsync -a "${wex[@]}" "$WIKI_MIRROR/" "$WIKI_DIR/"
    log "  + wiki/ → $WIKI_DIR"
  else
    warn "wiki 鏡像不存在：$WIKI_MIRROR（跳過）"
  fi

  log "IMPORT 完成。"
}

case "${1:-}" in
  export) do_export ;;
  import) do_import ;;
  audit)  run_secrets_audit ;;
  *)
    cat >&2 <<USAGE
用法：
  $(basename "$0") export   # .hermes/ + hermes-agent/ → 鏡像
  $(basename "$0") import   # 鏡像 → .hermes/ + hermes-agent/
  $(basename "$0") audit    # 只跑 secrets 掃描
USAGE
    exit 64
    ;;
esac
