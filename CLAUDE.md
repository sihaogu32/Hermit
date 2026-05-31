# CLAUDE.md

給未來進入 `hermit` 工作的 Claude Code session 的工作脈絡。專案完整介紹見 [`README.md`](README.md)、願景與設計見 [`docs/seed-spec.md`](docs/seed-spec.md)。

## 一句話定位

以 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 為基底的**個人化 AI agent**；繁中／台灣在地化 × 權限可控的個人資料脈絡 × 從研究到提醒到草稿的閉環執行。與法務專案 hermes_law 平行、獨立 repo，共用底座與架構模式但不搬法務資產。

## 設計紅線（5 條，single source = [`docs/seed-spec.md`](docs/seed-spec.md) §8）

1. **個人情境／領域是 first-class** — 按情境分層（health/finance/family…），不 hardcode 進 prompt/skill/tool 名。
2. **來源透明／可引用是必要防線** — 研究型回答附引用、個人化回答可追溯觸發來源；走 hook 強制，不只 prompt 紀律。
3. **不動 hermes-agent core 就不動** — 客製先走 skill / profile / config / plugin / tool；動 core 是最後手段（走 fork）。
4. **執行環境隔離** — 走 Docker（HERMES_HOME 在容器內 `/root/.hermes`）；狀態集中、可攜、鏡像備份。
5. **個人資料「不靜默自動動作」** — 任何寫入個人資料或對外執行的路徑都要有明確同意／人工確認入口；高風險動作（支付/下單/刪除）首版不自動。

## 核心約定（不要破壞）

1. **HERMES_HOME = 容器內 `/root/.hermes`；本 repo 只做鏡像備份** — 真實 runtime（含巢狀的 `~/.hermes/hermes-agent` source）不在 repo 內；repo 只保存 `.hermes-overlay/`（對應 `~/.hermes`）與 `patches/hermes-agent/`（對應 `~/.hermes/hermes-agent`）兩個 git 鏡像。安裝／重建 SOP 見 [`docs/install-runtime.md`](docs/install-runtime.md)
2. **客製化走擴充點，不改 hermes-agent core**（紅線#3）— 優先動 `.hermes/skills/`、`.hermes/memories/profiles/`、`.hermes/config.yaml`、`.hermes/SOUL.md`、`.hermes/plugins/`；程式能力的擴充落在 `hermes-agent/tools|scripts|tests/`（鏡像到 `patches/hermes-agent/`）；不要動 `hermes-agent/agent|gateway|hermes_cli|cron/` 等核心 module
3. **狀態 / 程式 / 知識 各歸其位**

   | 類型 | 位置 |
   |---|---|
   | 可執行程式 / 測試 | 真實在 `~/.hermes/hermes-agent/`；repo 只存鏡像 `patches/hermes-agent/files/`（+ 修改檔走 `diffs/`） |
   | hermes 個人知識庫（llm-wiki） | `wiki/` —— 鏡像 runtime `~/wiki`（hermes `/llm-wiki` 產物、使用者個人知識；**非** repo 開發紀錄處） |
   | runtime 狀態 | `~/.hermes/sessions/`、`~/.hermes/logs/`、`~/.hermes/state.db*` 等（不入 git、不入 overlay） |
   | 設計／安裝筆記 | `docs/`（seed-spec / install-runtime / roadmap / port-sources） |

4. **開發擴充的紀錄歸 Claude，不寫進 `wiki/`** — `wiki/` 是 hermes `/llm-wiki`（使用者個人知識庫）的鏡像，**不是** repo 開發紀錄的去處。新增程式／tool／connector／重要設定 → 在 `CLAUDE.md`、Claude 記憶或 `docs/` 留脈絡（用途、實際儲存路徑、執行／驗證方式）並補對應測試。擴充點與命名規則見下方「擴充點（Extension Slots）」一節
5. **擴充落地後跑 `scripts/sync_overlays.sh export` 並 commit** — 本地擴充靠 `.hermes-overlay/`、`patches/hermes-agent/`、`wiki/` 三個鏡像目錄備份；白名單／設定分別在各自的 `manifest.sh`（`wiki/` 為整目錄鏡像 runtime `~/wiki`）

## 擴充點（Extension Slots）

擴充原則：新功能落在既有責任邊界內，沒有邊界時先建立清楚邊界再實作；每個新增模組都要有對應測試或文件入口；情境／領域是 first-class（紅線#1），新增 health/finance/family… 是「加一個情境 + 一組 skill + 一個 connector」，不 hardcode 進 prompt/skill/tool 名。

客製化走以下其中一個 slot（呼應核心約定#2、紅線#3），不改 hermes-agent core：

1. **新 connector（個人資料源接入，P1 critical path）** — `.hermes/plugins/<connector-or-consent>/dashboard/{manifest.json,plugin_api.py,dist/index.js}`；測試 `.hermes/plugins/<name>/tests/test_<slug>_api.py`（檔名帶 `<slug>` 識別，避免合併 pytest 時 basename 撞名）；讀取工具落 `hermes-agent/tools/<feature>.py`（鏡像到 `patches/hermes-agent/files/`）；寫入／對外動作走「人工確認入口」（移植 [`docs/port-sources/legal-kb-admin/`](docs/port-sources/legal-kb-admin/)）。
2. **新 deterministic tool** — `hermes-agent/tools/<feature>.py` + `hermes-agent/tests/tools/test_<feature>.py`；若要進標準 toolset 改 `toolsets.py`。
3. **新 reusable skill** — `.hermes/skills/<domain>/<skill_name>/SKILL.md`，寫清 trigger 條件、確切指令、雷點、驗證。
4. **來源透明 guard（P2）** — `.hermes/plugins/source-guard/` + `hermes-agent/tools/<verify>.py`（移植 [`docs/port-sources/citation-guard/`](docs/port-sources/citation-guard/)）。

落地後跑 `scripts/sync_overlays.sh export` 推到鏡像再 commit：白名單見各自 `manifest.sh`（`.hermes-overlay` 的 `skills/* plugins/*` glob 已涵蓋，新 tool 要加進 `patches/hermes-agent/manifest.sh`）。

## 工作風格

- **先動手再迭代** — 面對陌生框架先裝起來跑過、產生具體 pain point 再談架構選型
- **小而可驗證** — 避免一次性大改；每個單元都要有對應測試或人工驗證步驟
- **Migration 而非重寫** — 移植 hermes_law 已驗證的「模式」（見 [`docs/port-sources/README.md`](docs/port-sources/README.md)），不直接沿用法務程式碼

## 目前進度

- **P0「專案落地」進行中**：已從 hermes_law 副本切出乾淨骨架（清掉法務資產、停放 port-sources 參考、重寫識別／設定／文件層、Docker 化）。
- 下一步 **P1（critical path）= connector + 權限同意中心 plugin**（移植 [`docs/port-sources/legal-kb-admin/`](docs/port-sources/legal-kb-admin/) 的 machine-proposes / human-confirms 形狀）。
- roadmap P0–P5 見 [`docs/roadmap.md`](docs/roadmap.md)。

## 常用驗證命令（Docker）

```powershell
# build（repo 根執行）
docker build -f docker/Dockerfile -t hermit .

# 管理後台 / 互動 CLI（secrets 走 -e 或 -v 掛 .env）
docker run --rm -p 9119:9119 -e OPENAI_API_KEY=... hermit web
docker run --rm -it -e OPENAI_API_KEY=... hermit cli
```

加 / 改 hermes tool 後要重啟或 reset 現行 hermes session，schema 才會被重新探索。

## 跑測試（自製擴充的 gate）

改完 tool / plugin 後跑 `scripts/run_tests.sh`——它從 manifest 衍生「自製測試清單」（tool 層 + plugin 層），從 runtime layout 執行：

```bash
# 本機（用真實 runtime ~/.hermes 與其 venv；不需 Docker）
scripts/run_tests.sh                                   # 跑全部自製測試
scripts/run_tests.sh -q -k calendar                    # 多餘參數原樣轉給 pytest
```

CI（`.github/workflows/tests.yml`）對每次 push / PR 自動跑同一套：clone 鎖定版 hermes-agent core（不裝 `.[all]` 195 套件）→ `sync_overlays.sh import` 組裝 → 裝 `ci/requirements-test.txt` 的最小 pin 版依賴 → 跑 `scripts/run_tests.sh`。新增 tool/plugin 測試只要照「擴充點」一節加進對應 manifest，CI 與本地 runner 都會自動納入；升級 hermes 版本鎖時，記得同步校 `ci/requirements-test.txt` 與 workflow 內的 `HERMES_AGENT_REF/SHA`。

## 文件導引

| 想了解 | 看這份 |
|---|---|
| 完整願景、市場前提、缺口分析、MVP、roadmap、設計紅線（single source） | [`docs/seed-spec.md`](docs/seed-spec.md) |
| Docker 安裝、執行、版本鎖、重建 SOP | [`docs/install-runtime.md`](docs/install-runtime.md) |
| 分期進度（P0–P5） | [`docs/roadmap.md`](docs/roadmap.md) |
| 移植來源參考（citation-guard / legal-kb-admin → hermit 改寫目標） | [`docs/port-sources/README.md`](docs/port-sources/README.md) |
| 目錄責任邊界、Extension Slots、命名規則 | 本檔上方「核心約定」與「擴充點（Extension Slots）」 |
