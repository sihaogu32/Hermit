---
title: Current Project Structure
created: 2026-05-28
updated: 2026-05-28
type: summary
tags: [hermes, personal-agent, architecture, codebase, tooling]
sources:
  - file:///C:/jeffrey/hermit/
  - file://~/.hermes/hermes-agent/AGENTS.md
  - file:///C:/jeffrey/hermit/wiki/SCHEMA.md
confidence: high
---

# Current Project Structure

本頁定義 `hermit` 目前專案的完整結構視圖，以及後續擴充時必須遵循的結構原則。

相關頁面：[[SCHEMA]]

## Structural Principles

1. 結構乾淨
   - source code、runtime state、wiki knowledge、tests 分層存放。
   - 不把 generated files、cache、venv、__pycache__ 當成架構的一部分。
   - 新功能應落在既有責任邊界內；沒有邊界時先建立清楚邊界再實作。

2. 結構易讀
   - 目錄名稱直接表達用途。
   - 每個新增模組都應有對應測試或文件入口。
   - wiki 內用 summary / entity / concept / comparison / query 分類。

3. 結構具備易擴充性
   - 個人能力以可替換單元擴充：skill、tool、connector plugin、wiki page。
   - **情境／領域是 first-class**：新增 health/finance/family… 是「加一個情境 page + 一組 skill + 一個 connector」，不 hardcode。
   - 後續新增資料源、工具或 workflow 時，應能新增子模組，而不是改壞既有核心。

## Repository Root

真實 runtime（HERMES_HOME，Docker 內 `/root/.hermes`，含巢狀 `hermes-agent`）不在 repo 內；repo 只保存 `.hermes-overlay/`（對應 `~/.hermes`）與 `patches/hermes-agent/`（對應 `~/.hermes/hermes-agent`）兩個 git 鏡像。

```text
hermit/
├── README.md / CLAUDE.md     # 人類入口 / Claude session 入口
├── docs/                     # 設計（seed-spec）、安裝、roadmap、port-sources 參考
├── docker/                   # 容器打包（Dockerfile + entrypoint + 指南）
├── scripts/sync_overlays.sh  # 鏡像 ↔ runtime 雙向同步
├── wiki/                     # LLM wiki；長期知識沉澱層
├── .hermes-overlay/          # ~/.hermes 擴充點的 git 鏡像（manifest.sh 維護白名單）
└── patches/hermes-agent/     # ~/.hermes/hermes-agent 內擴充的 git 鏡像（files/ + diffs/）

# 真實 runtime（容器內 / 家目錄，不在 repo 內）
~/.hermes/                    # HERMES_HOME（runtime state；上游預設）
├── config.yaml  SOUL.md  memories/  sessions/  skills/  plugins/  logs/  cron/  state.db*
└── hermes-agent/             # 巢狀的 NousResearch source（可執行程式與工具實作）
```

## Clean Boundary Model

- Implement executable behavior in `~/.hermes/hermes-agent/`（不在 repo 內；擴充靠 `patches/hermes-agent/` 鏡像回 repo）。
- Store stable project knowledge in `wiki/`。
- Treat `~/.hermes/sessions`、`logs`、`checkpoints`、`state.db*` as runtime state（不入 git、不入 overlay）。
- 任何 `~/.hermes/` 或 `~/.hermes/hermes-agent/` 內擴充落地後跑 `scripts/sync_overlays.sh export` 同步到鏡像，再 commit。

## Wiki Structure

```text
wiki/
├── SCHEMA.md              # wiki rules, page types, frontmatter, tags, update policy
├── index.md               # catalog of wiki pages
├── log.md                 # append-only wiki action log
├── project-structure.md   # this page
├── entities/              # notable systems, connectors, tools, services, data sources
├── concepts/              # architecture concepts and workflows
├── comparisons/           # side-by-side analyses
├── queries/               # substantial answers / research results
└── raw/                   # immutable source ingests
```

## Extension Slots

未來擴充應走以下其中一個 slot：

```text
1. 新情境／領域知識
   wiki/concepts/<situation>.md 或 wiki/entities/<thing>.md
   update index.md and log.md

2. 新 connector（個人資料源接入）— P1 critical path
   ~/.hermes/plugins/<connector-or-consent>/dashboard/{manifest.json,plugin_api.py,dist/index.js}
   ~/.hermes/plugins/<name>/tests/test_<slug>_api.py   # 檔名帶 <slug> 識別性，避免合併 pytest 時 basename 撞名
   讀取工具（若需）→ ~/.hermes/hermes-agent/tools/<feature>.py（鏡像到 patches/hermes-agent/files/）
   寫入 / 對外動作走「人工確認入口」（移植 docs/port-sources/legal-kb-admin 的 human-confirm）
   .hermes-overlay/manifest.sh 的 plugins/* glob 已涵蓋；新 tool 要加進 patches/hermes-agent/manifest.sh

3. 新 deterministic tool
   ~/.hermes/hermes-agent/tools/{feature}.py
   ~/.hermes/hermes-agent/tests/tools/test_{feature}.py
   toolsets.py registration（若要進標準 toolset）

4. 新 reusable agent workflow (skill)
   ~/.hermes/skills/<domain>/<skill_name>/SKILL.md
   include trigger conditions, exact commands, pitfalls, and verification
   .hermes-overlay/manifest.sh 的 skills/* glob 已涵蓋

5. 來源透明 guard（移植 docs/port-sources/citation-guard）— P2
   ~/.hermes/plugins/source-guard/ + ~/.hermes/hermes-agent/tools/<verify>.py
```

擴充落地後，跑 `scripts/sync_overlays.sh export` 把 `~/.hermes/` 與 `~/.hermes/hermes-agent/` 內的擴充推到鏡像目錄，再 commit。

## Extension Documentation Rule

任何新增的程式、script、tool、connector、資料結構或重要設定，都必須同步在 wiki 中留下紀錄：file purpose、actual storage path、why it belongs there、how to run/verify。若更動影響資料流（connector 讀寫順序、同意流程、agent 決策路徑），同步維護對應的流程圖／概念頁。

## Operational note

After adding or changing Hermes tools, restart/reset the active Hermes session so the tool schema is rediscovered.
