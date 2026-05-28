# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [2026-05-28] create | hermit repo 骨架落地（P0）
- 從法務專案 hermes_law（hinagiku）的完整副本切出獨立的個人化 agent repo `hermit`（命名見 seed-spec §10 #1）
- 清掉法務資產：`wiki/legal/`（62 部 KB + Activity_diagram + legal docs + sources/logs）、`wiki/map.md`、`legal-kb-browser` plugin、`skills/legal/`（fsc-penalty-search）、`legal_kb.py` / `legal_kb_pipeline.py` / `moj_kb_download.py` 及 legal 測試
- 停放移植來源為唯讀參考：`citation-guard`、`legal-kb-admin`、`verify_citation`（+ 對應 wiki 解說）移到 `docs/port-sources/`，附 README 對映到 hermit 改寫目標（§3.2 / §4 / §8）
- 重寫識別／設定層：`README.md`、`CLAUDE.md`、`.hermes-overlay/SOUL.md`（繁中 native、來源透明、不靜默自動動作）、`config.yaml`（移除 legal_kb toolset 與 legal plugins、language→zh-TW）、memories、兩個鏡像 README
- 重寫 wiki 知識層：`SCHEMA.md`（Domain + Tag Taxonomy 改個人 agent）、`project-structure.md`（hermit Extension Slots）、`index.md`（清空目錄）、本 log（fresh）
- 重寫 docs：seed spec 從 `docs/spinoff-personal-agent/` 畢業為 `docs/seed-spec.md`；`install-runtime.md` 改 Docker-on-Windows；`roadmap.md` 改 hermit P0–P5
- Docker 化：`Dockerfile` / `entrypoint.sh` 移除 legal KB 設定與健檢、`hinagiku`→`hermit`
- manifest / ignore：`.hermes-overlay/manifest.sh` 改 glob 槽（skills/* plugins/*）、`patches/hermes-agent/manifest.sh` 清空、`.gitignore` / `.dockerignore` 移除 legal 路徑
- `git init` 成新 repo
- 下一步 P1（critical path）：connector + 權限同意中心 plugin

## [2026-05-28] update | 文件漂移修正（roadmap git-init 狀態 / port-sources 連結對齊）
- `docs/roadmap.md`：P0 落地清單「`git init` + 初次 commit」狀態 `進行中` → `已實作（commit c83b651，working tree clean）`；P0 整體仍 `進行中`（Docker build/run 端到端驗證未跑）
- `README.md` / `CLAUDE.md`：文件導引中 port-sources 連結由裸目錄 `docs/port-sources/` 對齊為 `docs/port-sources/README.md`（指向對映表）
