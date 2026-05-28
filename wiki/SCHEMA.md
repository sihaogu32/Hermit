# Wiki Schema

## Domain
hermit 個人化 AI agent 的架構、擴充與知識工程：個人情境／領域（情境 first-class，如 health/finance/family…，不 hardcode）、connector（個人資料源接入）、權限同意中心、記憶與偏好治理、來源透明、以及在 hermes-agent 底座上的 skill / tool / plugin 擴充。

此 wiki 用來長期累積與維護：
- hermit 的架構決策、擴充模式、與 hermes_law 共用底座的關係
- 各個情境／領域的知識頁與其 connector / skill / plugin 對應
- 移植自 hermes_law 的模式（見 `../docs/port-sources/`）改寫成 hermit 版的設計與驗證
- 推理流程、資料來源、隱私／權限控管、驗證策略

## Conventions
- File names: lowercase, hyphens, no spaces，例如 `connector-consent-center.md`
- Every wiki page starts with YAML frontmatter
- Use `[[wikilinks]]` to link between pages; every new page should have at least 2 outbound links where feasible
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under the correct section
- Every action must be appended to `log.md`
- Raw sources under `raw/` are immutable; never edit raw files after ingest
- Prefer concrete implementation facts over vague descriptions

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

## raw/ Frontmatter

```yaml
---
source_url: file-or-url
ingested: YYYY-MM-DD
sha256: <hex digest of body only>
---
```

## Tag Taxonomy

Only use tags listed here. Add new tags here before using them.

### Personal Agent Domain
- personal-agent
- situation-domain
- memory-governance
- preferences
- source-transparency
- consent
- privacy

### Connectors & Data
- connector
- calendar
- notes
- cloud-files
- email
- data-source

### Hermes Base / Extension
- hermes
- skill
- plugin
- tooling
- integration
- gateway
- automation

### Software Architecture
- architecture
- codebase
- testing
- evaluation
- observability
- deployment
- security

### Knowledge Management
- source
- summary
- comparison
- query
- decision
- open-question

## Page Thresholds
- Create a page when an entity/concept appears in 2+ sources OR is central to one source
- Add to existing page when a source mentions something already covered
- DON'T create a page for passing mentions, minor implementation details, or temporary TODOs
- Split a page when it exceeds ~200 lines
- Archive a page when its content is fully superseded; move to `_archive/`, remove from index

## Entity Pages
One page per notable entity: a connector, tool, service, library, data source, model, API, plugin, or subsystem.
Include: overview, role in hermit, key facts/dates, relationships via `[[wikilinks]]`, source references.

## Concept Pages
One page per concept or topic: consent flow, source-transparency guard, situation-domain abstraction, memory governance, retrieval strategy, deployment boundary.
Include: definition, current implementation state, open questions, related concepts via `[[wikilinks]]`.

## Comparison Pages
Side-by-side analyses. Include what is being compared and why, dimensions (table), verdict, sources.

## Query Pages
File substantial answers that would be painful to reconstruct: architecture deep-dives, integration plans, workflow extraction, risk analyses, testing/evaluation strategy.

## Update Policy
When new information conflicts with existing content:
1. Check dates and source authority
2. If genuinely contradictory, note both positions with dates and sources
3. Mark with `contested: true` and `contradictions: [...]`
4. Flag for user review

## Porting Notes
When documenting a pattern ported from hermes_law (see `../docs/port-sources/`):
- Separate the original legal behavior from the proposed hermit implementation
- Preserve the reference path for traceability
- Identify user-facing behavior, data/permission dependencies, prompts, tests, and operational assumptions
- Prefer incremental units that can become hermit skills, tools, or plugins
- Record verification steps for each ported feature
