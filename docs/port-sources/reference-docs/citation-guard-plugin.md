---
title: citation-guard plugin
created: 2026-05-09
updated: 2026-05-09
type: summary
tags: [legal-agent, hermes, plugin, citation, redline-2, enforcement]
sources:
  - .hermes/plugins/citation-guard/plugin.yaml
  - .hermes/plugins/citation-guard/__init__.py
  - .hermes/plugins/citation-guard/tests/test_citation_guard.py
  - hermes-agent/hermes_cli/plugins.py
  - hermes-agent/run_agent.py
  - hermes-agent/model_tools.py
  - docs/citation-verification.md
confidence: high
---

# citation-guard plugin

對應設計紅線：[[../../docs/design-notes]] §設計紅線#2「Citation verification 是必要防線」。
對應 spec：[[../../docs/citation-verification]] §Enforcement 觸發層。
搭配工具：[[verify-citation]]、[[Activity_diagram/citation_guard_flow]]。

## 用途

`verify_citation` 工具落地後仍存在「agent 不呼叫」的繞道風險。本 plugin 走 hermes-agent v0.13 既有的 plugin hook 介面（不動 core）做事中強化 + 事後兜底 + audit，補齊事前紀律 SOUL.md 之外的三層 enforcement。

| 層 | 機制 | 角色 |
|---|---|---|
| 事前紀律 | `.hermes/SOUL.md` 紀律段 | 提升 first-pass 配合率（agent 配合 → final streaming 出來時已驗證 → 全程沒違規可洩漏） |
| 事中強化 | 本 plugin `transform_tool_result` | `verify_citation` status 非 `ok` 時強化 result 訊息提示 retry / 改用 ground truth |
| 事後兜底 | 本 plugin `transform_llm_output` | parse final response 中的法條引用，比對 per-session state；未驗證 / 失敗 → mutate response + 寫 violation log |
| Audit | 本 plugin `on_session_end` | dump 該 session 驗證統計（ok 數 / 總呼叫 / violation rate）到同檔，type 欄分流 |

## 儲存位置

```
$HERMES_HOME/plugins/citation-guard/
├── plugin.yaml
├── __init__.py
└── tests/
    └── test_citation_guard.py
```

`HERMES_HOME=~/.hermes`，因此實際路徑為 `~/.hermes/plugins/citation-guard/`。Project plugin 槽 — 由 `hermes_cli/plugins.py:_scan_directory` 第 3 條來源解析；CLAUDE.md 約定全部 hermes_law 客製 plugin 都放這層，不放 `hermes-agent/plugins/`（會被 upstream 覆蓋 / 衝突）。

> Project plugin 需 `HERMES_ENABLE_PROJECT_PLUGINS=1` 才會被掃；安裝 SOP 已於 `docs/install-runtime.md` 收斂。對齊紅線#5：本 plugin 出現在 `.hermes/` 下，本身被 `.gitignore` 擋，靠 `.hermes-overlay/` 鏡像備份。

## 三 hook 規格

### `transform_tool_result`

簽名（hermes-agent v0.13；以 `model_tools.py:794-811` 為準）：

```
transform_tool_result(
    tool_name, args, result, task_id, session_id, tool_call_id, duration_ms
) -> str | None
```

回非空字串則覆蓋 result（first-non-None wins）。本 plugin 行為：

1. 篩 `tool_name == "VerifyCitation"`，否則 return `None`
2. parse `result`（JSON 字串）抽 `law_name` / `normalized_article_no` / `status`
3. 寫入 per-session state：`_state[task_id|session_id][(law_name, no)] = status`
4. `status == "ok"` → return `None`（不修改）
5. 其他 status → return 強化版 result 字串：包含 `Citation guard` 警語 + 原 result（含 ground-truth `article_content`），讓下一輪 LLM 一眼看到要 retry / 改用 ground truth

### `transform_llm_output`

簽名（hermes-agent v0.13；以 `run_agent.py:14562-14575` 為準）：

```
transform_llm_output(response_text, session_id, model, platform) -> str | None
```

注意：**沒有 `task_id`**（觸發點在 turn 結束、tool loop 之外）；本 plugin 以 `session_id` 為鍵讀 state。

行為：

1. `_extract_citations(response_text)` parse 三型法條引用：
   - `《XX法》第 N 條`
   - `XX法第 N 條`
   - `XX法 第 N 條`
2. 條號 normalize：複用 `tools/verify_citation._try_normalize`（接受裸阿拉伯 / 「第 95-1 條」 / 「第八條」 / 「第九十五條之一」）
3. 比對 per-session state（`session_id` bucket）：
   - 全部引用都已驗證 `status="ok"` → return `None`
   - 任一引用未驗證或 status 非 `ok` → return mutate 後字串「[Citation guard] 偵測到未驗證引用，原回答已攔截」+ append jsonl 到 `$HERMES_HOME/logs/citation_violations/<YYYYMMDD>.jsonl`

### `on_session_end`

簽名（hermes-agent v0.13；以 `run_agent.py:14694-14708` 為準）：

```
on_session_end(session_id, completed, interrupted, model, platform) -> None
```

行為：

1. drain 該 session bucket（`_drain_state("", session_id)`）
2. 若無資料 → return（不寫空 record）
3. 統計 `verify_calls` / `verify_ok` / `violation_rate`
4. append jsonl 到同檔，`type="session_summary"`

## Per-session state 結構

```python
import threading

_state: dict[str, dict[tuple[str, str], str]] = {}
# key   = task_id or session_id or "default"
# value = {(law_name, normalized_article_no): status}
_lock = threading.Lock()
```

key 取 `task_id or session_id or "default"`（仿 hermes-agent bundled `disk-cleanup/` plugin 的慣例）。並發 hook 由 `_lock` 保護。記憶體中保存到 `on_session_end` 結算後 pop；不寫 disk（沒有狀態持久化需求）。

## Violation log 結構

`$HERMES_HOME/logs/citation_violations/<YYYYMMDD>.jsonl`（UTC date），兩種 record 同檔：

```json
{"type": "violation", "ts": "...", "session_id": "...", "model": "...", "platform": "...",
 "violations": [{"law_name": "公司法", "article_no": "8", "status": "unverified"}],
 "original_response": "..."}
{"type": "session_summary", "ts": "...", "session_id": "...", "completed": true,
 "interrupted": false, "verify_calls": 3, "verify_ok": 2, "violation_rate": 0.3333}
```

讀的時候依 `type` 欄分流。日誌目錄不入 git（`.hermes/logs/` 整層被 gitignore 擋）。

## 已知限制

對齊 spec §「此方案的誠實限制」：

- **streaming 期間短暫洩漏**：`transform_llm_output` 在 LLM streaming 完成後才跑；對偏離 SOUL.md 直接從記憶引用、且 final 迭代開始 streaming 的 agent，user 仍會在 streaming 過程中短暫看到 partial chunks（後 stored copy 被 mutate 覆寫，TUI / web frontend re-render 時顯示 mutate 後版本）。
- **配合 SOUL.md 的 agent 接近 100%**：因為走 verify path，final 出來時已正確，根本沒違規可洩漏。
- **regex-based 偵測會漏**：「第八條」/「第九十五條之一」中文「之 X」型若 normalize 失敗會被當作未驗證；條號夾在 markdown link / footnote / 多段引述中可能 miss。本 plugin 接受偽陰性（漏抓）大於偽陽性（誤攔）的 trade-off。
- **hard enforcement 沒做**：streaming 期間真要 100% 不洩漏需動 core（`run_agent.py` main tool loop 內加 `validate_before_final_stream` 點），spec §「動 core 的硬 enforcement 選項」已封存，未拍板。

## 測試

```bash
cd ~/.hermes/hermes-agent
venv/bin/python -m pytest \
  ~/.hermes/plugins/citation-guard/tests/test_citation_guard.py \
  -q -o 'addopts='
venv/bin/python -m py_compile ~/.hermes/plugins/citation-guard/__init__.py
```

12 個 test 覆蓋：

- `transform_tool_result`：`status="ok"` 不修改 + 寫 state；`status="content_mismatch"` 強化 result + 寫 state；非 `VerifyCitation` 工具忽略
- `transform_llm_output`：全引用驗證 `ok` 不改；有未驗證引用 mutate + 寫 violation log；有 `status != "ok"` 引用 mutate；無引用 return `None`
- 引用 regex 三型 + normalize：`《XX法》第 N 條` / `XX法第 N-M 條` / `XX法 第 N 條`、`第 95-1 條` ↔ `95-1` 鍵比對
- per-session state 隔離：`task_id_A` 不污染 `task_id_B`
- `on_session_end`：dump violation rate 寫 jsonl（`type="session_summary"`）；無 state 不寫空 record

## 維運

- 加 / 改 plugin hook 行為要回來更新本頁與 [[Activity_diagram/citation_guard_flow]]
- VALID_HOOKS 更名 / signature 變動以 `hermes-agent/hermes_cli/plugins.py` 為唯一真理；本 plugin 跟版本，不重複定義
- spec 更新（特別是 §動 core 的硬 enforcement 啟動條件）拍板後，本 plugin 才會被替代或補強
