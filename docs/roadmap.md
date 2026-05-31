# hermit roadmap（P0–P5）

承接 [`seed-spec.md`](seed-spec.md) §7 的開發順序：**先做資料與記憶治理 → 再對話與任務 → 再語音與整合 → 再代理工作流**（避免先做炫目自動化卻無權限／審計／記憶治理）。

> **本文件用途**：整理分期進度與下一步條件，不在這裡做新決策。決策在 `seed-spec.md` 對應段落拍板後，回頭更新本表狀態。

狀態圖示：`已決`（拍板未動工）·`進行中`·`已實作`·`未開工`·`待決`（等 pain point / 條件）·`blocked-by:...`

---

## 分期

| Phase | 目標 | 關鍵交付 | 狀態 |
|---|---|---|---|
| **P0** | 專案落地 | 從 hermes_law 副本切出乾淨 hermit 骨架（清法務資產、停放 port-sources、重寫識別／設定／文件層、Docker 化、`git init`） | **已實作（2026-05-29，含 build/run 端到端驗證）** |
| P1 | 資料與記憶治理（critical path） | **connector + 權限同意中心 plugin**（第一個資料源）、記憶可見／可編輯／可刪 | 進行中（consent-center 骨架已落地 2026-05-30；原生行事曆免授權核心已實作 2026-05-31；詳見下方「P1 進度」） |
| P2 | 對話與任務 | 繁中對話核心、提醒／排程、**來源透明 guard 移植**（citation-guard → source guard） | 進行中（來源透明 guard MVP 已實作 2026-05-31，見下方「P2 進度」；繁中對話核心／提醒排程未開工） |
| P3 | 整合與語音 | 第 2–3 個 connector、檔案／筆記摘要、語音輸入、草稿 | 未開工 |
| P4 | 商業化 | Freemium / Plus / Pro、B2B2C 綁定 | 未開工 |
| P5（後置） | hybrid / 離線 / 原生 app / 代理工作流 | on-device 路由、裝置端能力 | 待 pain point |

## P0 落地清單（2026-05-28）

| 項目 | 狀態 |
|---|---|
| 清法務資產（legal KB / legal-kb-browser / fsc-penalty-search / legal_kb 工具 / MOJ pipeline / legal wiki） | 已實作 |
| 停放 port-sources（citation-guard / legal-kb-admin / verify_citation → `docs/port-sources/`） | 已實作 |
| 重寫識別／設定層（README / CLAUDE / SOUL / config / memories / 鏡像 README） | 已實作 |
| 重寫 wiki 知識層（SCHEMA / project-structure / index / log） | 已實作 |
| 重寫 docs（seed-spec 畢業 / install-runtime Docker 化 / roadmap） | 已實作 |
| Docker 化（Dockerfile / entrypoint 去法務） | 已實作 |
| manifest / ignore 清法務、改 glob 槽 | 已實作 |
| `git init` + 初次 commit | 已實作（commit c83b651，working tree clean） |
| Docker build / run 端到端驗證 | 已實作（2026-05-29，rootless podman 5.6.2 跑通；build 15 步全過、smoke check `py_compile`+`hermes --help` 通過；run 驗證 entrypoint 透傳／`cli` 別名／overlay 還原／`hermes doctor` exit 0。建置方法未動 Dockerfile，僅以臨時 registries.conf 解 podman 短名）。**版本鎖已 bump 至 `v2026.5.29`（SHA `e71a2bd1` = package v0.15.1，距上游 HEAD 113 commits），image 2.47 GB** |

## P1 進度（2026-05-30）

第一刀 = 權限同意中心 plugin 骨架（落實紅線#5「個人資料不靜默自動動作」）：用 staging fixture 跑通 machine proposes → human confirms（proposal schema 已預留 source 欄）。第一個資料源已落地為**原生行事曆免授權核心**（2026-05-31，三源合併：原生 events.json 主 + ICS 主推 + Google 降選配唯讀 adapter；方向改版見 [`docs/migration/google-calendar-connector-plan.md`](docs/migration/google-calendar-connector-plan.md)）。

| 項目 | 狀態 / 落地位置 |
|---|---|
| consent-center dashboard plugin（六端點 proposals/confirm/cancel/history） | 已實作 `.hermes/plugins/consent-center/dashboard/{manifest.json,plugin_api.py,dist/index-0.1.0.js}` |
| 受管寫入工具（唯一寫入入口、**非** agent tool） | 已實作 `hermes-agent/tools/consent_memory.py`（module body 無 top-level `registry.register` → `_module_registers_tools` 回 False；寫自有受管檔 `memories/managed/CONFIRMED.md`，不碰 core MEMORY.md/USER.md） |
| dev-only 提議工具（toolset `consent-dev` 預設關，只寫 staging） | 已實作 `hermes-agent/tools/consent_propose_tool.py`（feature 內唯一 register 點） |
| pytest（含紅線守門 + 紅線回歸，18 passed） | 已實作 `.hermes/plugins/consent-center/tests/test_consent_center_api.py`；驗證 `cd ~/.hermes/hermes-agent && venv/bin/python -m pytest ~/.hermes/plugins/consent-center/tests/ -q -o 'addopts='`（自製擴充全套 `scripts/run_tests.sh` 為 76 passed） |
| 鏡像白名單 + sync export | 已實作（`.hermes-overlay/manifest.sh`、`patches/hermes-agent/manifest.sh` 逐檔加；export 無 warn、secrets 掃描通過） |
| 原生行事曆免授權核心（三源合併視圖） | 已實作（commit 3d0298f）：`calendar_store.py`／`calendar_read.py`／`consent_event.py` + `plugins/calendar` dashboard（月/週/列表 + 手動增刪改）；Google 既有 read tool 改造成唯讀 source adapter（`google_calendar.py`）；agent 新增走 `propose_event` → consent。**下一段**：ICS 抓取/解析（需 icalendar，deferred stub 已備位）、Google OAuth 真實端到端驗證 |
| 記憶可見／可編輯／可刪 | 未開工 |

## P2 進度（2026-05-31）

來源透明 guard 移植（citation-guard / verify_citation → hermit 版），落實紅線#2「走 hook 強制，不只 prompt 紀律」。把法務「權威來源＝法規 KB」換成 hermit「答案依據＝web 連結／個人記憶」，沿用同一套 hook 架構（事前 SOUL ／事中 transform_tool_result ／事後 transform_llm_output ／audit on_session_end）。

| 項目 | 狀態 / 落地位置 |
|---|---|
| source-guard hook plugin（事中 grounding + 事後攔截 + audit） | 已實作 `.hermes/plugins/source-guard/{plugin.yaml,__init__.py}`：`transform_tool_result` 蒐集本回合工具抓取過的 URL（排除 VerifySource 自我 echo）；`transform_llm_output` 偵測 final response 中未追溯連結（本回合沒抓過＝杜撰強訊號）依 mode 處置；`on_session_end` dump 統計到 `logs/source_violations/<YYYYMMDD>.jsonl`。grounding 採網域層級比對（接受偽陰性 > 偽陽性，同 citation-guard 哲學） |
| 來源驗證工具 VerifySource（事前主動驗證入口） | 已實作 `hermes-agent/tools/verify_source.py`：`memory`→對記憶庫（MEMORY.md／USER.md／managed/*.md）標準化內容比對回 ok/not_found；`url`→external（離線不抓取，提醒只引用實際抓過的連結）。唯讀工具、toolset `source-guard` |
| 事前紀律 | 已補強 `SOUL.md` 來源透明段（只引用本回合實際抓取過的連結；引用記憶前可用 VerifySource） |
| 啟用 | 已掛上：`config.yaml` `plugins.enabled: [source-guard]` + `toolsets`／`platform_toolsets.cli` 加 `source-guard`。預設 `HERMIT_SOURCE_GUARD_MODE=block`（攔截取代未追溯回答），可設 `annotate`（保留原文加警示）或 `off`（純記錄）。**下次重啟 hermes session 生效** |
| pytest（tool 13 + plugin 16） | 已實作 `tests/tools/test_verify_source.py`、`.hermes/plugins/source-guard/tests/test_source_guard.py`；`scripts/run_tests.sh` 全套 **105 passed**（tool 62 + plugin 43） |
| **下一段** | 繁中對話核心、提醒／排程；先觀察 `logs/source_violations` 的偽陽性率，再決定是否收緊（如改 path-level grounding、把 research-no-source 從 log-only 升為提示） |

## 開放決策（承接 seed-spec §10）

| # | 待決 | 狀態 / 條件 |
|---|---|---|
| 1 | 專案命名 + 新 repo | **已決：hermit** |
| 2 | 部署模型：單人工具 / 多人 / SaaS | 待決；跑通單人 MVP 後評估 |
| 3 | **第一個 connector**：行事曆 / 筆記 / 雲端檔 / 郵件 | **已決：行事曆**（改版 2026-05-31：原生免授權核心為主、ICS 主推匯入、Google OAuth 降級保留作進階選項；見 [`docs/migration/google-calendar-connector-plan.md`](docs/migration/google-calendar-connector-plan.md)） |
| 4 | 行動端：messaging gateway 起步 vs 原生 app | 待決；gateway 可快速驗證 |
| 5 | 起始族群是否鎖 26–35 歲知識工作者 | 待決 |
| 6 | 私有 Google Drive 需求文件納入 | 待決；納入後回頭修訂 seed-spec |

## 維護規則

- 每完成一項，把狀態改成 `已實作` / `已決`，補上落地位置與驗證方式
- 不要在 roadmap 做決策——決策在 `seed-spec.md` 做完後再回頭更新本表
- 任何欄位修改在 commit message 說明即可（`wiki/` 是 hermes 個人知識庫鏡像，不放 repo 開發紀錄）
