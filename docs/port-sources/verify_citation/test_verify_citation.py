"""verify_citation 工具測試（對應 docs/citation-verification.md §落地清單）。"""

import json
from pathlib import Path

from tools import verify_citation as vc


def _company_law():
    return {
        "LawName": "公司法",
        "LawModifiedDate": "20230615",
        "LawArticles": [
            {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 一 章 總則"},
            {
                "ArticleType": "A",
                "ArticleNo": "第 8 條",
                "ArticleContent": (
                    "本法所稱公司負責人：在無限公司、兩合公司為執行業務或代表公司之股東；"
                    "在有限公司、股份有限公司為董事。"
                ),
            },
            {
                "ArticleType": "A",
                "ArticleNo": "第 95-1 條",
                "ArticleContent": (
                    "公司之清算人，於執行清算事務範圍內，除本法另有規定外，其權利義務與董事同。"
                ),
            },
        ],
    }


def _fhc_law():
    return {
        "LawName": "金融控股公司法",
        "LawModifiedDate": "20230208",
        "LawArticles": [
            {
                "ArticleType": "A",
                "ArticleNo": "第 1 條",
                "ArticleContent": "為發揮金融機構綜合經營效益，特制定本法。",
            },
        ],
    }


def _chapter_only_law():
    return {
        "LawName": "保險法",
        "LawModifiedDate": "20240101",
        "LawArticles": [
            {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "第 一 章 總則"},
            {
                "ArticleType": "A",
                "ArticleNo": "第 1 條",
                "ArticleContent": "本法所稱保險，謂當事人約定。",
            },
        ],
    }


def _write_kb(tmp_path: Path, *laws: dict) -> Path:
    kb_dir = tmp_path / "wiki" / "legal" / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)
    index_payload = []
    for law in laws:
        name = law["LawName"]
        d = kb_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text(json.dumps(law, ensure_ascii=False), encoding="utf-8")
        index_payload.append({"law_name": name, "description": f"{name} 一句索引描述"})
    (kb_dir / "index.json").write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")
    return kb_dir


def test_law_not_found_returns_fuzzy_candidates(tmp_path):
    kb_dir = _write_kb(tmp_path, _fhc_law(), _company_law())

    result = vc.verify_citation("金融控股公司", "1", kb_dir=str(kb_dir))

    assert result["status"] == "law_not_found"
    assert result["article_content"] == ""
    assert result["normalized_article_no"] == "1"
    assert "金融控股公司法" in result["candidates"]
    assert len(result["candidates"]) <= 3
    # L2.a — law_not_found 不該有 citation_block（無 ground-truth 法名）
    assert "citation_block" not in result
    assert "本法名未在 KB 中" in result["usage_instruction"]


def test_article_not_found_with_existing_law(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "999", kb_dir=str(kb_dir))

    assert result["status"] == "article_not_found"
    assert result["law_name"] == "公司法"
    assert result["law_modified_date"] == "20230615"
    assert result["article_content"] == ""
    assert "candidates" not in result
    # L2.a — article_not_found 但有 ground-truth 法名：citation_block 仍要產
    assert result["citation_block"] == "《公司法》第 999 條"
    assert "GetLawToc" in result["usage_instruction"]


def test_normalize_full_form_with_dash(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "第 95-1 條", kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    assert result["normalized_article_no"] == "95-1"
    assert "清算人" in result["article_content"]
    # L2.a — citation_block 用中文書名號 + 引用指示
    assert result["citation_block"] == "《公司法》第 95-1 條"
    assert "以 citation_block 開頭" in result["usage_instruction"]


def test_normalize_chinese_numeral(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "第八條", kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    assert result["normalized_article_no"] == "8"
    assert "公司負責人" in result["article_content"]
    assert result["citation_block"] == "《公司法》第 8 條"


def test_normalize_bare_number(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "8", kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    assert result["normalized_article_no"] == "8"
    assert result["citation_block"] == "《公司法》第 8 條"


def test_chinese_numeral_with_appendix(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "第九十五條之一", kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    assert result["normalized_article_no"] == "95-1"
    assert result["citation_block"] == "《公司法》第 95-1 條"


def test_content_match_ok(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    quoted = "本法所稱公司負責人 在無限公司、兩合公司，為執行業務或代表公司之股東。"
    result = vc.verify_citation("公司法", "8", quoted_text=quoted, kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    assert result["match_detail"]["matched"] is True
    assert result["match_detail"]["method"] == "normalized_substring"
    # L2.a/c — 有 quoted_text 不該出 warning；usage_instruction 為 ok+quoted 版本
    assert "warning" not in result
    assert "不得改寫法名與條號" in result["usage_instruction"]


def test_content_mismatch_returns_ground_truth(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    quoted = "公司負責人為任何持有公司股份超過百分之五十之股東（捏造）"
    result = vc.verify_citation("公司法", "8", quoted_text=quoted, kb_dir=str(kb_dir))

    assert result["status"] == "content_mismatch"
    assert "公司負責人" in result["article_content"]
    assert result["match_detail"]["matched"] is False
    # L2.a — content_mismatch 仍有 citation_block + 對應 usage_instruction
    assert result["citation_block"] == "《公司法》第 8 條"
    assert "改用回傳的 article_content 原文" in result["usage_instruction"]


def test_quoted_text_none_skips_match_detail(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "8", quoted_text=None, kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    assert "match_detail" not in result
    # L2.c — 無 quoted_text 時必出 warning + ok-without-quoted 版 usage_instruction
    assert "未提供 quoted_text" in result["warning"]
    assert "建議下次補 quoted_text" in result["usage_instruction"]
    assert result["citation_block"] == "《公司法》第 8 條"


def test_chapter_header_excluded(tmp_path):
    """ArticleType='C' 章節標題不會被當條文命中。"""
    kb_dir = _write_kb(tmp_path, _chapter_only_law())

    # 餵章節風格 article_no（normalize 失敗 → article_not_found）
    result = vc.verify_citation("保險法", "第 一 章", kb_dir=str(kb_dir))
    assert result["status"] == "article_not_found"
    assert result["normalized_article_no"] == ""
    # normalize 失敗 → 無 citation_block，但仍提供 usage_instruction
    assert "citation_block" not in result
    assert "GetLawToc" in result["usage_instruction"]

    # 確認真條文（A 型）仍能命中
    ok = vc.verify_citation("保險法", "1", kb_dir=str(kb_dir))
    assert ok["status"] == "ok"
    assert "本法所稱保險" in ok["article_content"]
    assert ok["citation_block"] == "《保險法》第 1 條"


def test_handler_returns_json_string_with_success_envelope(tmp_path):
    kb_dir = _write_kb(tmp_path, _company_law())

    raw = vc._verify_citation_handler(
        {"law_name": "公司法", "article_no": "第八條", "kb_dir": str(kb_dir)}
    )
    payload = json.loads(raw)

    assert payload["success"] is True
    assert payload["status"] == "ok"
    assert payload["normalized_article_no"] == "8"
    # 無 quoted_text 案例：handler 應一併傳遞新欄位
    assert payload["citation_block"] == "《公司法》第 8 條"
    assert "建議下次補 quoted_text" in payload["usage_instruction"]
    assert "未提供 quoted_text" in payload["warning"]


def test_out_of_range_chinese_numeral_falls_to_article_not_found(tmp_path):
    """千位以上 raise → caller 收成 article_not_found（不靜默吃）。"""
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "第一千條", kb_dir=str(kb_dir))

    assert result["status"] == "article_not_found"
    assert result["normalized_article_no"] == ""
    # normalize 失敗使 normalized="" → 不發 citation_block；usage_instruction 仍導向 GetLawToc
    assert "citation_block" not in result
    assert "GetLawToc" in result["usage_instruction"]


# ---------------------------------------------------------------------------
# L2.a / L2.c 新增 test
# ---------------------------------------------------------------------------


def test_citation_block_uses_book_title_marks(tmp_path):
    """L2.a — citation_block 必須用《》中文書名號 + 條號 anchor。"""
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("公司法", "第八條", kb_dir=str(kb_dir))

    assert result["status"] == "ok"
    block = result["citation_block"]
    assert block.startswith("《")
    assert "》第 " in block
    assert block.endswith("條")
    assert block == "《公司法》第 8 條"


def test_warning_only_when_quoted_text_missing(tmp_path):
    """L2.c — warning 欄位只在 quoted_text=None 時出現。"""
    kb_dir = _write_kb(tmp_path, _company_law())

    quoted = "本法所稱公司負責人 在無限公司、兩合公司，為執行業務或代表公司之股東。"
    with_quoted = vc.verify_citation(
        "公司法", "8", quoted_text=quoted, kb_dir=str(kb_dir)
    )
    without_quoted = vc.verify_citation("公司法", "8", kb_dir=str(kb_dir))

    assert with_quoted["status"] == "ok"
    assert "warning" not in with_quoted

    assert without_quoted["status"] == "ok"
    assert "warning" in without_quoted
    assert "未提供 quoted_text" in without_quoted["warning"]


def test_law_not_found_has_no_citation_block(tmp_path):
    """L2.a — law_not_found 不該有 citation_block（無 ground-truth 法名）。"""
    kb_dir = _write_kb(tmp_path, _company_law())

    result = vc.verify_citation("不存在的法", "1", kb_dir=str(kb_dir))

    assert result["status"] == "law_not_found"
    assert "citation_block" not in result
    assert "本法名未在 KB 中" in result["usage_instruction"]
