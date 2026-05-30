# hermit

以 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 為基底的**個人化 AI agent**。不是「另一個更會聊天的 AI」，而是以**繁體中文與台灣生活脈絡**為核心的「個人知識與任務中樞」——持續記住偏好、跨來源整合個人資料、把答案變成可執行的提醒／草稿，且讓使用者看得見依據、控制得了記憶與權限。

與法務專案 hermes_law 平行、各自獨立 repo，共用同一個 hermes-agent 上游底座與已驗證的架構模式，但不共用 running instance、不搬法務資產。完整願景、市場前提、設計紅線、roadmap 見 [`docs/seed-spec.md`](docs/seed-spec.md)。

> **狀態（2026-05-28）**：P0「專案落地」進行中——已從 hermes_law 副本切出乾淨骨架（清掉法務資產、保留可重用底座），執行環境走 Docker。下一步 P1 = connector + 權限同意中心（critical path）。

## 目錄結構

真實 runtime（`~/.hermes`，含 `~/.hermes/hermes-agent`）在容器內 HERMES_HOME、不在 repo 內；repo 只保存 `.hermes-overlay/`（對應 `~/.hermes`）與 `patches/hermes-agent/`（對應 `~/.hermes/hermes-agent`）兩個 git 鏡像。

```text
# repo（git-tracked）
hermit/
├── README.md / CLAUDE.md     # 人類入口 / Claude session 入口
├── docs/                     # 設計（seed-spec）、安裝、roadmap、port-sources 參考
├── wiki/                     # 長期知識沉澱層（人 + agent 共讀）
├── docker/                   # 容器打包（Dockerfile + entrypoint）
├── scripts/sync_overlays.sh  # 鏡像 ↔ runtime 雙向同步
├── .hermes-overlay/          # 對應 ~/.hermes 擴充點的 git 鏡像
└── patches/hermes-agent/     # 對應 ~/.hermes/hermes-agent 內擴充的 git 鏡像（files/ + diffs/）

# 真實 runtime（容器內 / 家目錄，不在 repo 內）
~/.hermes/                    # HERMES_HOME（runtime 狀態；上游預設）
└── hermes-agent/             # 巢狀的 NousResearch source
```

## 快速開始（Docker）

```powershell
# build（從 repo 根；context=repo 根、-f 指向 docker/Dockerfile）
docker build -f docker/Dockerfile -t hermit .

# 管理後台（9119）
docker run --rm -p 9119:9119 -e OPENAI_API_KEY=... hermit web

# 互動 CLI
docker run --rm -it -e OPENAI_API_KEY=... hermit cli
```

secrets 一律 runtime 提供（`-e *_API_KEY` 或 `-v` 掛 `~/.hermes/.env`），image 內不含。安裝細節、版本鎖、重建 SOP 見 [`docs/install-runtime.md`](docs/install-runtime.md)。

## 設計紅線（5 條）

1. **個人情境／領域是 first-class** — 不把單一情境 hardcode 進 prompt/skill/tool 名。
2. **來源透明／可引用是必要防線** — 走 hook 強制，不只 prompt 紀律。
3. **不動 hermes-agent core 就不動** — 客製先走 skill / profile / config / plugin / tool。
4. **執行環境隔離** — 走 Docker；狀態集中在 HERMES_HOME、可攜、鏡像備份。
5. **個人資料「不靜默自動動作」** — 寫入個人資料或對外執行需明確同意／人工確認入口。

詳見 [`docs/seed-spec.md`](docs/seed-spec.md) §8。

## 文件導引

| 想了解 | 看這份 |
|---|---|
| 完整願景、市場前提、缺口分析、MVP、roadmap、設計紅線 | [`docs/seed-spec.md`](docs/seed-spec.md) |
| Docker 安裝、執行、版本鎖、重建 SOP | [`docs/install-runtime.md`](docs/install-runtime.md) |
| 分期進度（P0–P5） | [`docs/roadmap.md`](docs/roadmap.md) |
| 移植來源（citation-guard / legal-kb-admin）參考 | [`docs/port-sources/README.md`](docs/port-sources/README.md) |
| 目錄責任邊界、Extension Slots、開發約定 | [`CLAUDE.md`](CLAUDE.md) |
