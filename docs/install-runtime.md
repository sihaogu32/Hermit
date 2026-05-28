# 安裝與執行期約定（Docker）

hermit 的執行環境走 **Docker 容器**：HERMES_HOME 在容器內 `/root/.hermes`（上游預設），hermes-agent source 巢狀在 `/root/.hermes/hermes-agent`。靠容器邊界與法務（hermes_law）完全隔離，跨平台、可攜、可重現。

> 設計紅線#4（執行環境隔離、狀態集中在 HERMES_HOME）見 [`seed-spec.md`](seed-spec.md) §8。本節是該紅線在 Docker 下的具體實作（single source）。

## 真實 runtime 與 repo 的關係

**真實 runtime（容器內 `/root/.hermes`，含巢狀的 `hermes-agent`）不在 repo 內。** repo 只保存它的 git-tracked 鏡像：

| repo 內（入 git） | 對應的容器內位置（不入 git） |
|---|---|
| `.hermes-overlay/` | `/root/.hermes/`（擴充點：SOUL.md、config.yaml、plugins、skills、memories） |
| `patches/hermes-agent/files/` | `/root/.hermes/hermes-agent/`（新增檔；目前無） |
| `patches/hermes-agent/diffs/` | `/root/.hermes/hermes-agent/`（修改既有上游檔的 git patch；目前無） |

兩者由 [`scripts/sync_overlays.sh`](../scripts/sync_overlays.sh) 雙向同步（`export` 推鏡像、`import` 還原）；`docker build` 期會自動跑 `import` 把鏡像疊回容器內 runtime。

### wiki/（llm-wiki 知識層）— 例外：baked + symlink，不走 sync

`wiki/` 直接 git-tracked 在 repo 頂層，**不在 overlay/patches manifest 內、不由 `sync_overlays.sh` 同步**。它由 `docker build` 的 `COPY . /opt/hermit/` 帶進 image，再 `ln -sfn /opt/hermit/wiki /root/wiki` symlink 到 llm-wiki skill（`research/llm-wiki`）預設讀取路徑 `~/wiki`（容器內 `HOME=/root`）。

因此 **image 內就備妥一份打好基底的 wiki**（`SCHEMA.md`/`index.md`/`log.md` + `raw/`、`entities/`、`concepts/`、`comparisons/`、`queries/` 內容層），啟動 agent 後 skill 即可直接讀寫，不需另行擴充。

> runtime 寫入會落在容器層（重建即消失、不回 git）。dev 時要讓 skill 的產出持久回 repo，把 host 的 `<repo>/wiki` bind-mount 到容器 `/opt/hermit/wiki`（`-v <repo>/wiki:/opt/hermit/wiki`）。

## Build

從 repo 根執行（build context = repo 根、`-f` 指向 `docker/Dockerfile`）：

```powershell
docker build -f docker/Dockerfile -t hermit .
# 可指定上游版本（預設鎖 v2026.5.16）
docker build -f docker/Dockerfile --build-arg HERMES_AGENT_REF=v2026.5.16 -t hermit .
```

build 內部（細節見 [`docker/Dockerfile`](../docker/Dockerfile)）：
1. base：`git clone NousResearch/hermes-agent` 到 `/root/.hermes/hermes-agent` 並 `checkout` 鎖定 tag
2. `setup-hermes.sh` 建 venv + `uv pip install -e ".[all]"`（~195 套件）+ 同步 bundled skills
3. `COPY . /opt/hermit/` → 跑 `sync_overlays.sh import` 把鏡像（overlay + patches）疊回 `/root/.hermes`
4. 中性 smoke 健檢（py_compile + `hermes --help`）

> **版本鎖**：用 git tag / commit 鎖上游（如 `v2026.5.16` = SHA `a91a57fa5`），不要用 pyproject 的 package version（`0.14.0` 橫跨多個 release、不唯一）。若 `patches/diffs/` 有改上游既有檔的 patch，`git apply` 才挑版本；目前 `diffs/` 為空，硬失敗風險低。

## Run

secrets 一律 runtime 提供，image 內不含。期望（擇一）：
- `-v C:\path\to\.env:/root/.hermes/.env:ro`
- `-e OPENAI_API_KEY=...` / `-e ANTHROPIC_API_KEY=...` / `-e OPENROUTER_API_KEY=...`

```powershell
# 管理後台（9119）— 預設子命令
docker run --rm -p 9119:9119 -e OPENAI_API_KEY=... hermit            # 等同 hermit web
docker run --rm -p 9119:9119 -e OPENAI_API_KEY=... hermit web

# gateway chat（8642，OpenAI 相容）
docker run --rm -p 8642:8642 -e OPENAI_API_KEY=... hermit run

# 互動 CLI
docker run --rm -it -e OPENAI_API_KEY=... hermit cli

# 任意 hermes 子命令直接透傳
docker run --rm -e OPENAI_API_KEY=... hermit doctor
```

> hermes web/run 預設 bind `127.0.0.1`；用 `-p` 對映 port 從 host 連。entrypoint 細節見 [`docker/entrypoint.sh`](../docker/entrypoint.sh)。

## 客製化擴充點（不動 source 的前提下）

進入容器內 `/root/.hermes/` 後，做個人版特化主要動這些（改完跑 `sync_overlays.sh export` 鏡像回 repo）：

| 路徑 | 用途 |
|---|---|
| `/root/.hermes/SOUL.md` | agent 整體人格、語氣、邊界（繁中 native、來源透明、不靜默自動動作） |
| `/root/.hermes/config.yaml` | 模型、tool、gateway、UI 設定 |
| `/root/.hermes/plugins/<name>/` | dashboard plugin（P1：connector + 同意中心） |
| `/root/.hermes/skills/<domain>/<skill>/` | 自製 skill |
| `/root/.hermes/memories/profiles/` | 不同 profile 的 user profile |
| `/root/.hermes/.env` | API key、外部服務 endpoint（**不入 git**） |

## 重建 SOP

```powershell
# 0.（換機）clone repo
git clone <hermit-repo-url> hermit; cd hermit

# 1. rebuild image（base 會重新 clone 鎖版本的 hermes-agent + sync import 疊回擴充）
docker build -f docker/Dockerfile -t hermit .

# 2. 補 secrets（不在 git）：跑時 -v 掛 .env 或 -e 帶 *_API_KEY
docker run --rm -p 9119:9119 -v C:\secrets\.env:/root/.hermes/.env:ro hermit web
```

> 開發期若要在本機（非容器）對 `~/.hermes` 動擴充再 `sync_overlays.sh export`，需要一個 Linux 環境（WSL / 容器內）跑該 bash 腳本；目前 hermit 的標準路徑是容器內 build-time import + 直接改 repo 鏡像。
