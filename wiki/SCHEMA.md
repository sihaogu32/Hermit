# Wiki Schema

## Domain
個人知識管理：整理使用者長期關注的主題、閱讀筆記、研究素材、決策脈絡、個人工作流、工具使用心得，以及值得累積的問題答案。

這個 wiki 的目標不是保存所有零碎資訊，而是把「未來會重複查、需要交叉引用、或值得逐步深化」的知識編成可維護的 markdown 知識網。

## Conventions
- File names: lowercase, hyphens, no spaces，例如 `personal-knowledge-management.md`。
- Every wiki page starts with YAML frontmatter（見下方 Frontmatter）。
- Use `[[wikilinks]]` to link between pages；每個新頁面至少 2 個 outbound links。若 wiki 還太小導致暫時不足，先連到最接近的概念頁，後續補強。
- When updating a page, always bump the `updated` date。
- Every new page must be added to `index.md` under the correct section。
- Every action must be appended to `log.md`。
- Raw sources in `raw/` are immutable：讀取可以，除重新 ingest 或修正 frontmatter/hash 外，不直接改寫內容。
- **Provenance markers:** On pages that synthesize 3+ sources, append `^[raw/articles/source-file.md]` 或相對 raw path at the end of paragraphs whose claims come from a specific source.

## Frontmatter
```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [from taxonomy below]
sources: [raw/articles/source-name.md]
# Optional quality signals:
confidence: high | medium | low
contested: true
contradictions: [other-page-slug]
---
```

`confidence` and `contested` are recommended for subjective, fast-changing, or weakly sourced personal workflows and research claims.

## raw/ Frontmatter
Raw sources also get a small frontmatter block so re-ingests can detect drift:

```yaml
---
source_url: https://example.com/article
ingested: YYYY-MM-DD
sha256: <hex digest of the raw content below the frontmatter>
---
```

Compute `sha256` over the body only（closing `---` 之後的內容），not the frontmatter.

## Tag Taxonomy
Only use tags listed here. Add a new tag here before using it.

### Knowledge Types
- note
- concept
- framework
- method
- workflow
- decision
- question
- summary

### Personal / Work Context
- personal
- productivity
- learning
- research
- writing
- planning
- tools
- automation

### Source / Quality
- book
- article
- paper
- transcript
- meeting
- reference
- evergreen
- contested

### Meta
- comparison
- timeline
- index
- archive

## Page Thresholds
- **Create a page** when an entity/concept appears in 2+ sources OR is central to one source.
- **Add to existing page** when a source mentions something already covered.
- **DON'T create a page** for passing mentions, minor details, or things outside the domain.
- **Split a page** when it exceeds ~200 lines — break into sub-topics with cross-links.
- **Archive a page** when its content is fully superseded — move to `_archive/`, remove from index.

## Entity Pages
One page per notable entity, such as a person, organization, product, tool, book, course, or project. Include:
- Overview / what it is
- Key facts and dates
- Relationships to other entities using `[[wikilinks]]`
- Source references

## Concept Pages
One page per reusable concept or topic. Include:
- Definition / explanation
- Why it matters in this personal knowledge system
- Current understanding
- Open questions or debates
- Related concepts using `[[wikilinks]]`

## Comparison Pages
Side-by-side analyses. Include:
- What is being compared and why
- Dimensions of comparison, preferably table format
- Verdict or synthesis
- Sources

## Query Pages
Save only non-trivial answers that would be painful to re-derive. Include:
- Question
- Short answer
- Evidence from existing wiki pages and sources
- Follow-up questions or next actions

## Update Policy
When new information conflicts with existing content:
1. Check source dates and context — newer sources may supersede older ones, but personal preferences may depend on situation.
2. If genuinely contradictory, note both positions with dates and sources.
3. Mark the contradiction in frontmatter: `contradictions: [page-name]` and/or `contested: true`.
4. Flag for user review in the lint report.
