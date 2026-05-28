# hermit roadmap（P0–P5）

承接 [`seed-spec.md`](seed-spec.md) §7 的開發順序：**先做資料與記憶治理 → 再對話與任務 → 再語音與整合 → 再代理工作流**（避免先做炫目自動化卻無權限／審計／記憶治理）。

> **本文件用途**：整理分期進度與下一步條件，不在這裡做新決策。決策在 `seed-spec.md` 對應段落拍板後，回頭更新本表狀態。

狀態圖示：`已決`（拍板未動工）·`進行中`·`已實作`·`未開工`·`待決`（等 pain point / 條件）·`blocked-by:...`

---

## 分期

| Phase | 目標 | 關鍵交付 | 狀態 |
|---|---|---|---|
| **P0** | 專案落地 | 從 hermes_law 副本切出乾淨 hermit 骨架（清法務資產、停放 port-sources、重寫識別／設定／文件層、Docker 化、`git init`） | **進行中（2026-05-28）** |
| P1 | 資料與記憶治理（critical path） | **connector + 權限同意中心 plugin**（第一個資料源）、記憶可見／可編輯／可刪 | 未開工 |
| P2 | 對話與任務 | 繁中對話核心、提醒／排程、**來源透明 guard 移植**（citation-guard → source guard） | 未開工 |
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
| Docker build / run 端到端驗證 | 待跑（需 Docker Desktop + 網路） |

## 開放決策（承接 seed-spec §10）

| # | 待決 | 狀態 / 條件 |
|---|---|---|
| 1 | 專案命名 + 新 repo | **已決：hermit** |
| 2 | 部署模型：單人工具 / 多人 / SaaS | 待決；跑通單人 MVP 後評估 |
| 3 | **第一個 connector**：行事曆 / 筆記 / 雲端檔 / 郵件 | 待決；P1 開工前拍板（建議從「高頻 + 風險可控 + 易感知價值」選） |
| 4 | 行動端：messaging gateway 起步 vs 原生 app | 待決；gateway 可快速驗證 |
| 5 | 起始族群是否鎖 26–35 歲知識工作者 | 待決 |
| 6 | 私有 Google Drive 需求文件納入 | 待決；納入後回頭修訂 seed-spec |

## 維護規則

- 每完成一項，把狀態改成 `已實作` / `已決`，補上落地位置與驗證方式
- 不要在 roadmap 做決策——決策在 `seed-spec.md` 做完後再回頭更新本表
- 任何欄位修改要在 [`../wiki/log.md`](../wiki/log.md) 留一筆紀錄
