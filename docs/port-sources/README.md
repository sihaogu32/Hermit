# port-sources/ — 移植來源（唯讀參考，非執行檔）

這裡停放的是從法務專案 hermes_law 帶過來的**已驗證架構模式**，spec（[`../seed-spec.md`](../seed-spec.md)）點名要把這些「模式」改寫進 hermit，但**不直接沿用法務程式碼**。

> ⚠ **這些檔不會被載入 runtime**。它們不在 `.hermes-overlay/` / `patches/` 鏡像白名單內，`docker build` 的 `sync_overlays.sh import` 不會碰到，hermes 也不會載。純粹給 P1/P2 改寫時當參考。原始 active 版本仍在 hermes_law repo（Linux），那邊是權威來源。

## 對映表：參考 → hermit 改寫目標

| 停放物 | 原始角色（法務） | hermit 改寫目標 | spec 段落 |
|---|---|---|---|
| `citation-guard/` | 4 層 hook 強制法條引用驗證（SOUL 事前／`transform_tool_result` 事中／`transform_llm_output` 事後／`on_session_end` audit） | **來源透明 guard**：研究型回答附引用、個人化回答標觸發來源、記憶引用可追溯。同一套 hook 架構，把「權威來源＝法規 KB」換成「答案依據＝web／個人資料源／memory id」 | §3.2、§8#2（紅線#2）、P2 |
| `verify_citation/` | 被 citation-guard 包夾的核心驗證工具（法名／條號／內容比對） | 來源驗證工具：對個人資料源／web 來源做存在性與內容比對 | §8#2、P2 |

> ✅ **已落地（2026-05-31）**：`citation-guard/` → `.hermes/plugins/source-guard/`、`verify_citation/` → `hermes-agent/tools/verify_source.py`（見 [`../roadmap.md`](../roadmap.md) §P2 進度）。法規 KB 內容比對改為「web 連結 grounding（本回合抓過才可引用）＋個人記憶內容比對」。此二參考可保留對照，亦可在確認 hermit 版穩定後移除。`legal-kb-admin/` 仍為 P1 connector／同意中心的對照參考。
| `legal-kb-admin/` | dashboard plugin，machine-proposes / human-confirms：cron 寫 scan dump → 人工 dashboard 按鈕才 apply（唯一寫入入口走 `POST /scans/{id}/confirm`） | **connector + 權限同意中心**：任何「機器自己動了個人資料／對外執行」都要有人按；唯一寫入入口走 plugin | §4（critical path）、§8#5（紅線#5）、P1 |

## reference-docs/

對應的 wiki 解說與流程圖（法務脈絡），改寫時對照用：
- `citation-guard-plugin.md`、`citation_guard_flow.md` — citation-guard 三 hook 規格與流程
- `verify-citation.md`、`verify_citation_flow.md` — 驗證工具回傳 schema 與內部流程
- `legal-kb-admin-plugin.md`、`moj-kb-pipeline-stage-c.md` — human-confirm plugin 與 scan 生命週期

## 改寫落地後

把改寫好的 hermit 版 plugin / 工具放回 active 位置（`.hermes/plugins/<name>/`、`.hermes/hermes-agent/tools/`），加進對應 manifest，`sync_overlays.sh export`、補 wiki page；屆時此資料夾可整個刪除。
