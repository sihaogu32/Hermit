# syntax=docker/dockerfile:1
###############################################################################
# hermit 個人化 AI agent — 打包 image
#
# HERMES_HOME=~/.hermes（容器內 = /root/.hermes），
# hermes-agent 巢狀在 $HERMES_HOME/hermes-agent（上游非 root 預設落點）。
#
# 兩段式：① base = 鎖定版本的 hermes；② 疊上「A. 我的調校」(repo 鏡像)。
#   A（.hermes-overlay/ + patches/ + sync 腳本）→ COPY 進來、sync import 疊回 runtime
#     wiki/ → COPY 進 /opt/hermit/wiki 後 symlink 到 ~/wiki（llm-wiki skill 預設路徑；image 內備妥基底 wiki）
#   B（上游 core + Python 環境）→ git clone 並鎖版本
#   C（secrets）/ D（runtime 狀態）→ 不打包；C runtime 注入(-e/-v)、D 用 volume
#
# build（從 repo 根執行，context=repo 根；-f 指向 docker/Dockerfile）：
#   docker build -f docker/Dockerfile --build-arg HERMES_AGENT_REF=v2026.5.16 -t hermit .
###############################################################################
FROM nikolaik/python-nodejs:python3.11-nodejs20

# ── B：鎖定上游版本 ──────────────────────────────────────────────────────
# ⚠ 用 git tag/commit 鎖，不要用「0.14.0」：
#   0.14.0 是 pyproject.toml 的 package version，橫跨多個 release、不唯一；
#   上游 release 是 CalVer git tag（如 v2026.5.16）。要可重現就鎖完整 commit SHA
#   或 CalVer tag，最好＝你 sync_overlays.sh export 當下的版本（patches/diffs 若有改
#   上游既有檔的 patch，git apply 才挑版本；本專案目前 diffs/ 為空，硬失敗風險低）。
#   查已安裝版本：git -C ~/.hermes/hermes-agent rev-parse HEAD
ARG HERMES_AGENT_REPO=https://github.com/NousResearch/hermes-agent.git
ARG HERMES_AGENT_REF=v2026.5.16

ENV HERMES_HOME=/root/.hermes \
    PATH="/root/.local/bin:${PATH}" \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep rsync ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

# ── ① base：鎖定版本的 hermes，巢狀安裝在 $HERMES_HOME/hermes-agent ──────────
RUN git clone "${HERMES_AGENT_REPO}" "${HERMES_HOME}/hermes-agent" \
 && git -C "${HERMES_HOME}/hermes-agent" checkout "${HERMES_AGENT_REF}" \
 && git -C "${HERMES_HOME}/hermes-agent" rev-parse HEAD > "${HERMES_HOME}/.hermes-agent-pinned-sha"
# setup-hermes.sh：建 venv + uv pip install -e ".[all]"(195 套件) + 同步 74 bundled skills
RUN cd "${HERMES_HOME}/hermes-agent" \
 && yes n | env HERMES_HOME="${HERMES_HOME}" bash setup-hermes.sh

# ── ② 疊上 A：我的調校（hermit repo 鏡像）────────────────────────────────
# .dockerignore 已排除本地 hermes-agent/、.hermes/（避免把 venv/secrets/狀態烤進來）
COPY . /opt/hermit/
# 從 repo 鏡像還原到 $HERMES_HOME：overlay→~/.hermes、patches/files→hermes-agent、diffs→git apply
RUN cd /opt/hermit && bash scripts/sync_overlays.sh import

# ── wiki：llm-wiki skill 的知識庫 ────────────────────────────────────────────
# wiki/ 不走 overlay manifest（直接 git-tracked 在 repo 頂層）：上面的 COPY 已帶進 /opt/hermit/wiki。
# 這裡 symlink 到 llm-wiki skill（research/llm-wiki）預設讀取路徑 ~/wiki（容器內 HOME=/root）。
# → image 內即備妥一份打好基底的 wiki（SCHEMA/index/log + raw/entities/concepts/comparisons/queries），
#   啟動後可直接被 skill 讀寫，不需另行擴充。
RUN ln -sfn /opt/hermit/wiki /root/wiki

# ── build 時健檢（中性 smoke：確認 base 裝好、overlay import 成功）────────────
RUN cd "${HERMES_HOME}/hermes-agent" \
 && venv/bin/python -m py_compile toolsets.py \
 && venv/bin/hermes --help > /dev/null

# 9119 = hermes web 管理後台；8642 = gateway chat
EXPOSE 9119 8642

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
