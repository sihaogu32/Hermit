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

## [2026-05-29] update | P0 收尾：Docker build/run 端到端驗證跑通
- 環境：本機 docker daemon inactive/disabled 且使用者不在 `docker` 群組，改用 **rootless podman 5.6.2**（Fedora 預設）跑同一份 `docker/Dockerfile`，等同驗證；唯一外掛是臨時 `registries.conf`（`unqualified-search-registries=["docker.io"]` + `short-name-mode=permissive`）解 podman 對短名 base image 的解析，**Dockerfile 未改**
- build：15 步全過，base `python3.11-nodejs20` pull → 鎖版 clone `v2026.5.16`（commit `a91a57fa5` = release v0.14.0）→ `setup-hermes.sh` 建 venv＋裝相依 → overlay import（SOUL/config/memories 還原）→ build 時 smoke check `py_compile toolsets.py` + `hermes --help` 通過。產出 `localhost/hermit:latest`（2.54 GB）
- run 驗證：① entrypoint 透傳 `hermes --help` 正常、無金鑰時警告如期印到 stderr；② `cli` 別名分支（shift→hermes）正常；③ `hermes version` = `v0.14.0 (2026.5.16)` 對上版本鎖；④ overlay 還原確認（`config.yaml` toolsets 已清為 `hermes-cli`、SOUL/MEMORY/USER 就位）；⑤ `hermes doctor` exit 0，核心工具與目錄結構全綠，剩餘 ⚠ 皆為預期（無 secrets／可選工具未裝／config v22→v23 小版差）
- `docs/roadmap.md`：P0 整體 `進行中` → `已實作（2026-05-29，含 build/run 端到端驗證）`；P0 落地清單最後一列「Docker build/run 端到端驗證」`待跑` → `已實作` 並補驗證方式
- 下一步：P1（critical path）connector + 權限同意中心 plugin；開工前先拍板開放決策 #3「第一個 connector」

## [2026-05-29] update | 版本鎖 bump v2026.5.16 → v2026.5.29
- 動機：前次驗證的鎖版 `v2026.5.16`（package v0.14.0）距上游已 1445 commits；上游最新 release tag 為 `v2026.5.29`（今日）
- 改動：`docker/Dockerfile`（`ARG HERMES_AGENT_REF` + 2 處註解示例）、`docs/install-runtime.md`（build 範例 + 版本鎖說明）由 `v2026.5.16` → `v2026.5.29`；對應 SHA 由 `a91a57fa5` → `e71a2bd1`。`wiki/log.md` 既有歷史紀錄（5.16 那次 build）為 append-only，不回改
- 重新驗證（podman，同 registries.conf）：build exit 0、clone 落在 `e71a2bd11 chore: release v0.15.1 (2026.5.29)`、容器內 `.hermes-agent-pinned-sha` = `e71a2bd11b733f3be7cf99deafde0066c343d462`、`hermes version` = `v0.15.1 (2026.5.29)`、`hermes doctor` exit 0；距上游 HEAD 由 1445 → 113 commits，image 2.47 GB
- `docs/roadmap.md`：P0 落地清單驗證列補上 bump 後的版本／SHA／size
