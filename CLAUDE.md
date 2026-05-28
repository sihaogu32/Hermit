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
   | 長期知識（人 + agent 共讀） | `wiki/` |
   | runtime 狀態 | `~/.hermes/sessions/`、`~/.hermes/logs/`、`~/.hermes/state.db*` 等（不入 git、不入 overlay） |
   | 設計／安裝筆記 | `docs/`（seed-spec / install-runtime / roadmap / port-sources） |

4. **加東西要同步寫 wiki** — 新檔在 `hermes-agent/` → 在 `wiki/` 留 page 解釋用途、儲存位置、執行／驗證方式；每次動作 append 到 `wiki/log.md`，新 page 加進 `wiki/index.md`。Extension Slots / Naming Rules 見 [`wiki/project-structure.md`](wiki/project-structure.md)
5. **擴充落地後跑 `scripts/sync_overlays.sh export` 並 commit** — 本地擴充靠 `.hermes-overlay/` 與 `patches/hermes-agent/` 兩個鏡像目錄備份；白名單分別在各自的 `manifest.sh`

## 工作風格

- **先動手再迭代** — 面對陌生框架先裝起來跑過、產生具體 pain point 再談架構選型
- **小而可驗證** — 避免一次性大改；每個單元都要有對應測試或人工驗證步驟
- **Migration 而非重寫** — 移植 hermes_law 已驗證的「模式」（見 [`docs/port-sources/`](docs/port-sources/)），不直接沿用法務程式碼

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

## 文件導引

| 想了解 | 看這份 |
|---|---|
| 完整願景、市場前提、缺口分析、MVP、roadmap、設計紅線（single source） | [`docs/seed-spec.md`](docs/seed-spec.md) |
| Docker 安裝、執行、版本鎖、重建 SOP | [`docs/install-runtime.md`](docs/install-runtime.md) |
| 分期進度（P0–P5） | [`docs/roadmap.md`](docs/roadmap.md) |
| 移植來源參考（citation-guard / legal-kb-admin → hermit 改寫目標） | [`docs/port-sources/README.md`](docs/port-sources/README.md) |
| 目錄責任邊界、Extension Slots、Naming Rules | [`wiki/project-structure.md`](wiki/project-structure.md) |
| Wiki 自身規則（frontmatter、page types、log policy） | [`wiki/SCHEMA.md`](wiki/SCHEMA.md) |
