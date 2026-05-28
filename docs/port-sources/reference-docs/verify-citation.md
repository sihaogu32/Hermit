---
title: verify_citation 工具
created: 2026-05-09
updated: 2026-05-09
type: summary
tags: [legal-agent, hermes, citation, redline-2, tool]
sources:
  - hermes-agent/tools/verify_citation.py
  - hermes-agent/tests/tools/test_verify_citation.py
  - docs/citation-verification.md
confidence: high
---

# verify_citation 工具

對應設計紅線：[[../../docs/design-notes]] §設計紅線#2「Citation verification 是必要防線」。
對應 spec：[[../../docs/citation-verification]]。

相關頁面：[[legal-kb-programs]]、[[Activity_diagram/verify_citation_flow]]、[[../map]]

## 用途

法務領域對「捏造法條」零容忍：

- **Mata v. Avianca (2023)** — 美國律師因 ChatGPT 捏造判例遭法院制裁
- **Stanford HAI 2024** — 量到 LexisNexis Lexis+ AI、Thomson Reuters Westlaw AI Assistant 仍有 17–33% 幻覺率

`verify_citation` 是 spec 對紅線#2 的 MVP 落地形狀，責任：

1. 確認 `(法名, 條號)` 在本地 L2 curated KB 真的存在
2. 若 agent 提供 `quoted_text`，再做標準化內容比對（移空白 + 移常見中英標點 + substring containment）
3. **任一失敗狀態都回 ground-truth `ArticleContent`**，給 agent 自我修正錨點

## 程式檔位置

| 用途 | 路徑 |
|---|---|
| 工具實作 | `hermes-agent/tools/verify_citation.py` |
| 工具測試 | `hermes-agent/tests/tools/test_verify_citation.py` |

## 工具簽名

```python
def verify_citation(
    law_name: str,                    # "公司法" / "金融控股公司法"
    article_no: str,                  # "8" / "95-1" / "第八條" / "第 95-1 條" / "第九十五條之一"
    quoted_text: str | None = None,   # None 跳過內容比對
    kb_dir: str | None = None,        # 顯式 KB 路徑（測試 / 多 KB 環境用）
) -> dict
```

KB 解析優先序沿用 legal_kb：顯式 `kb_dir` arg → `HERMES_LEGAL_KB_DIR` → `<HERMES_HOME 父層>/wiki/legal/knowledge_base`。

## 回傳 schema

```json
{
  "status": "ok | law_not_found | article_not_found | content_mismatch",
  "normalized_article_no": "95-1",
  "law_name": "金融控股公司法",
  "article_content": "<KB ground-truth；status 任一狀態都回傳，供 agent 自我修正>",
  "law_modified_date": "20230208",
  "candidates": ["金融控股公司法", "金融機構合併法"],
  "match_detail": {
    "matched": true,
    "method": "normalized_substring",
    "normalized_query_excerpt": "...",
    "normalized_article_excerpt": "..."
  }
}
```

欄位語意：

- `status` — 四值之一：`ok`（存在 + 內容過關 / 沒做內容比對）、`law_not_found`、`article_not_found`、`content_mismatch`
- `article_content` — KB ground truth；status 非 `ok` 時為空字串或 ground truth（agent 可拿來自我修正）
- `candidates` — 僅 `law_not_found` 時填，由 `difflib.get_close_matches` 對 `index.json` 內 `law_name` 鍵（**小寫**）取前 3
- `match_detail` — 僅有 `quoted_text` 時填

## 核心邏輯

1. **法名 lookup** — load `<KB>/<law_name>/<law_name>.json`；找不到則對 `index.json` 全表 fuzzy（fuzzy 對 `index.json` 內 `law_name` 鍵；spec 文字寫成 `LawName` 是 source ChLaw.json 的概念欄，落地時讀的是小寫 `law_name`）
2. **條號 normalize** — 先試 `tools/legal_kb.py:_normalize_article_no()`（接受裸條號 / 「第 95-1 條」）；失敗 fallback 中文數字薄層（接受「第八條」/「第九十五條之一」），範圍 1-999 + 附條
3. **條文 lookup** — 複用 `tools/legal_kb.py:_build_article_index()`；`ArticleType == "A"` 才算（章節標題 `"C"` 排除）
4. **內容比對** — 兩邊 `re.sub(r"\s+", "", ...)` + 移除常見中英標點（句逗、引號、頓號、括號、冒號、分號、問號、驚嘆號等），再做 substring containment
5. **失敗永遠回 ground-truth `ArticleContent`** — 給 agent 一個明確的修正錨點

## Toolset 註冊

掛在既有 `legal_kb` toolset，與 GetIndex / GetLawToc / GetLawArticle / GetLawSummary / GetLawDetail / RunDownloadAndScan 並列；新檔載入時直接 `registry.register(name="VerifyCitation", toolset="legal_kb", ...)`，不動 `toolsets.py`。詳見 [[legal-kb-programs]]。

## 維運

- 加 / 改工具後要重啟 hermes session 才能讓 schema 重新探索
- 純讀 KB；不寫狀態
- enforcement（plugin / SOUL.md / on_session_end audit）走 [[citation-guard-plugin]]（Stage 2 落地後）

## 已知限制

- MVP 僅法條，不驗判例（spec §不在 MVP 範圍）
- 不做項款 / 但書粒度（KB 將整條文存在 `ArticleContent`，到「條」就停）
- KB miss 直接回 `law_not_found` + 候選；不打 live MOJ
- 中文數字薄層僅支援 1-999 + 附條；千 / 萬 / 億級條號 raise → 由 caller 收成 `article_not_found`，不靜默吃

## 驗證命令

```bash
cd hermes-agent
venv/bin/python -m pytest tests/tools/test_verify_citation.py -q -o 'addopts='
venv/bin/python -m py_compile tools/verify_citation.py
```

測試覆蓋：法不存在（含 fuzzy candidates 排序）、條不存在、條號 normalize 三型（裸 / 「第 95-1 條」/ 「第八條」/ 「第九十五條之一」）、內容 hit / 內容 miss + ground truth 回、`quoted_text=None` 跳過 `match_detail`、`ArticleType="C"` 章節排除、handler JSON 包裝、超出範圍中文數字 → `article_not_found`。
