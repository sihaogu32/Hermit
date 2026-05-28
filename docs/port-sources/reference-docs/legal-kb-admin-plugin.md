---
title: legal-kb-admin Plugin（MOJ KB 人工確認 / 歷史）
created: 2026-05-07
updated: 2026-05-09
type: summary
tags: [legal-agent, hermes, plugin, dashboard, moj, kb]
sources:
  - .hermes/plugins/legal-kb-admin/
  - hermes-agent/tools/legal_kb.py
  - docs/migration/moj-kb-stage-c-impl-plan.md
confidence: high
---

# legal-kb-admin Plugin

## 用途

階段 C 把 MOJ KB pipeline 的「**人工確認**」與「**執行歷史**」包進 hermes
dashboard。本 plugin **只做兩件事**：

1. 列出 cron 觸發 agent 寫入的 pending scan，讓使用者勾選 / 確認後 apply
2. 列出歷史 changelog（`extract_*.json`）讓使用者回看 article-level diff

**不做**的事：

- cron 排程 CRUD — 走 hermes 內建 cron 頁面 / CLI（`hermes cron`）
- 立即觸發按鈕 — 階段 C 範圍外
- 進度 polling / SSE — apply 是同步一次性動作，response 收完即完成
- `/run` `/status` `/reset` 等狀態機 endpoints

設計紅線「apply 必須由人工在 dashboard 上確認」由兩處保證：
`tools/legal_kb.py` **不**註冊 `RunApply*` 為 agent tool；唯一可寫的入口
是 plugin 的 `POST /scans/{id}/confirm`。

## 儲存位置

| 路徑 | 內容 | 是否進 git |
|---|---|---|
| `.hermes/plugins/legal-kb-admin/dashboard/manifest.json` | tab 註冊 | 鏡像至 `.hermes-overlay/` |
| `.hermes/plugins/legal-kb-admin/dashboard/plugin_api.py` | FastAPI router（六端點） | 同上 |
| `.hermes/plugins/legal-kb-admin/dashboard/dist/index-0.1.0.js` | 前端 IIFE bundle | 同上 |
| `.hermes/plugins/legal-kb-admin/tests/test_legal_kb_admin_api.py` | pytest 整合測試（識別性檔名，避免 pytest basename 撞名） | 同上 |
| `HERMES_HOME/legal_kb_scans/{scan_id}.json` | **runtime** 待確認 scan 暫存區 | 不入 git、不入 overlay |
| `wiki/legal/logs/change/extract_*.json` | 歷史 changelog（apply 後寫） | 不入 git（gitignore `/wiki/legal/logs/`） |

## API schema

| Method | Path | 行為 |
|---|---|---|
| `GET` | `/api/plugins/legal-kb-admin/scans` | 列舉 `legal_kb_scans/*.json`，回 `{scans: [{scan_id, created_at, source_used, summary}]}`，依 `created_at` 倒序 |
| `GET` | `/api/plugins/legal-kb-admin/scans/{scan_id}` | 回完整 scan dump payload（含 `scan.article_diffs`、`new`/`changed`/`obsolete`、`filtered_laws`） |
| `POST` | `/api/plugins/legal-kb-admin/scans/{scan_id}/confirm` | body `{laws?: list[str], delete_obsolete?: bool}`；同步呼叫 `tools.legal_kb.run_apply_selected`；成功回 `{applied, summaries, changelog_path}`；失敗 500 + traceback |
| `POST` | `/api/plugins/legal-kb-admin/scans/{scan_id}/cancel` | 刪該 scan 檔；404 if 不存在 |
| `GET` | `/api/plugins/legal-kb-admin/history?limit=50` | 列 `wiki/legal/logs/change/extract_*.json` 最新 N 筆精簡 `{filename, timestamp_utc, counts}` |
| `GET` | `/api/plugins/legal-kb-admin/history/{filename}` | 回單筆完整 changelog payload（含 `article_diffs`） |

異常一律 raise `HTTPException(status_code, detail=traceback.format_exc())`，前端
拿到後 inline 顯示。`{scan_id}` / `{filename}` 走 `_safe_filename` 防止跨目錄
存取，且 `{filename}` 必須以 `extract_` 開頭、`.json` 結尾。

## 與 hermes cron 的分工

```
   ┌───────────── hermes cron job（hermes-agent/cron/）─────────────┐
   │  schedule: every 7d                                            │
   │  enabled_toolsets: legal_kb                                    │
   │  deliver: telegram                                             │
   │  prompt: 「請執行 RunDownloadAndScan...附 dashboard 連結」      │
   └─────────────────────┬──────────────────────────────────────────┘
                         │ 60s tick → AIAgent 一輪對話
                         ▼
       agent 呼叫 RunDownloadAndScan 工具
                         │
                         ▼
       run_download_and_scan() 下載 MOJ → 比對 KB → 算 article-level diff
                         │
                         ▼
       dump 到 HERMES_HOME/legal_kb_scans/{scan_id}.json
                         │
                         ▼ agent 寫摘要 + 內嵌 dashboard 連結
       deliver=telegram → 推到 Telegram 主頻道
                                                │
                                                ▼ 使用者點連結
                              http://localhost:9119/legal-kb-admin?scan_id=xxx
                                                │
                                                ▼ panel 自動展開該 scan
                                          [ 三欄 + diff + 勾選 ]
                                                │
                                                ▼ 套用選定 / 取消此 scan
                                  POST /api/plugins/legal-kb-admin/scans/{id}/confirm
                                  POST /api/plugins/legal-kb-admin/scans/{id}/cancel
                                                │
                                                ▼ 同步呼叫
                              run_apply_selected → apply_extraction
                                                 → generate_summaries
                                                 → 刪 scan 檔
                                                │
                                                ▼
                              KB 更新 + extract_*.json 寫入
                                                │
                                                ▼
                              history panel refresh，新 changelog 出現
```

cron 端不直接 apply、不夾帶 confirm 邏輯；apply / cancel 完全由使用者
在 plugin UI 上觸發。

## scan 檔生命週期

| 狀態 | 動作 |
|---|---|
| 不存在 | 待 cron 喚醒 agent 觸發 `RunDownloadAndScan` |
| 寫入 `legal_kb_scans/{scan_id}.json` | agent 把 scan_id 拼進 dashboard 連結，由 deliver 推到 Telegram |
| 待人工處理 | 在 dashboard 列表顯示，標 created_at + counts |
| confirm | `run_apply_selected` 套用後，自動 `unlink` scan 檔 |
| cancel | plugin endpoint 直接 `unlink` scan 檔 |
| 過時不處理 | 留在 `legal_kb_scans/` 直到使用者 cancel；不會自動過期 |

## cron job 範例（落地後使用者執行，不入 git）

```bash
HERMES_HOME=~/.hermes hermes cron create "every 7d" \
  "請執行 RunDownloadAndScan 工具下載最新 MOJ 全國法規資料庫並掃描變更。
完成後請以中文摘要列出 new / changed / obsolete 三類法規（僅列名稱與數量，不要列每條條文）。
最後請務必附上這個確認連結（用回傳的 scan_id 替換）：
http://localhost:9119/legal-kb-admin?scan_id={scan_id}

注意：你只能呼叫 RunDownloadAndScan，不要嘗試 apply。Apply 必須由使用者在 dashboard 上人工確認。" \
  --deliver "telegram" \
  --name "MOJ KB 週掃描"
```

`hermes cron create` CLI 目前未暴露 `--enabled-toolsets` flag（底層 `cron.jobs.create_job` 接受此參數），cron job 觸發的 agent 會拿到完整 toolset；以 prompt 文字「你只能呼叫 RunDownloadAndScan，不要嘗試 apply」約束。需要硬性限制可用工具時，改用 Python 直接呼 `cron.jobs.create_job(enabled_toolsets=["legal_kb"], ...)` 建。

`hermes cron list / pause / resume / remove` 走既有 cron 頁面或 CLI，
plugin 不重複實作。

## 執行 / 驗證方式

### 單元測試（plugin 端）

```bash
cd ~/.hermes/hermes-agent
venv/bin/python -m pytest \
  ~/.hermes/plugins/legal-kb-admin/tests/ \
  -q -o 'addopts='
```

### 單元測試（tools 端，shared primitives）

```bash
cd ~/.hermes/hermes-agent
venv/bin/python -m pytest tests/tools/test_legal_kb.py -q -o 'addopts='
```

### Dashboard render sanity

```bash
HERMES_HOME=~/.hermes hermes dashboard   # default 9119
chrome --headless --disable-gpu --dump-dom \
  http://localhost:9119/legal-kb-admin
```

完整 e2e（真網路下載 + 真 Telegram + 真 cron）見
[`docs/migration/moj-kb-stage-c-impl-plan.md` §驗證計畫](../../docs/migration/moj-kb-stage-c-impl-plan.md)。

## 相關 page

- [[legal/legal-kb-programs]] — `tools/legal_kb.py` 五工具 + `RunDownloadAndScan` schema
- [[legal/legal-kb-browser-plugin]] — 瀏覽 KB 的 read-only sibling plugin
- [[legal/Activity_diagram/moj_download_flow]] — 下載 + 比對的純函式流程
- [[legal/Activity_diagram/moj-kb-pipeline-stage-c]] — 階段 C 兩條路徑活動圖
