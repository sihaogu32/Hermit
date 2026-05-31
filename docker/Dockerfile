# syntax=docker/dockerfile:1
###############################################################################
# hermit 個人化 AI agent — 打包 image
#
# HERMES_HOME=~/.hermes（容器內 = /root/.hermes），
# hermes-agent 巢狀在 $HERMES_HOME/hermes-agent（上游非 root 預設落點）。
#
# 兩段式：① base = 鎖定版本的 hermes；② 疊上「A. 我的調校」(repo 鏡像)。
#   A（.hermes-overlay/ + patches/ + wiki/ + sync 腳本）→ COPY 進來、sync import
#   B（上游 core + Python 環境）→ git clone 並鎖版本
#   C（secrets）/ D（runtime 狀態）→ 不打包；C runtime 注入(-e/-v)、D 用 volume
#
# build（從 repo 根執行，context=repo 根；-f 指向 docker/Dockerfile）：
#   docker build -f docker/Dockerfile --build-arg HERMES_AGENT_REF=v2026.5.29 -t hermit .
###############################################################################
FROM nikolaik/python-nodejs:python3.11-nodejs20

# ── B：鎖定上游版本 ──────────────────────────────────────────────────────
# ⚠ 用 git tag/commit 鎖，不要用「0.14.0」：
#   0.14.0 是 pyproject.toml 的 package version，橫跨多個 release、不唯一；
#   上游 release 是 CalVer git tag（如 v2026.5.29）。要可重現就鎖完整 commit SHA
#   或 CalVer tag，最好＝你 sync_overlays.sh export 當下的版本（patches/diffs 若有改
#   上游既有檔的 patch，git apply 才挑版本；本專案目前 diffs/ 為空，硬失敗風險低）。
#   查已安裝版本：git -C ~/.hermes/hermes-agent rev-parse HEAD
ARG HERMES_AGENT_REPO=https://github.com/NousResearch/hermes-agent.git
ARG HERMES_AGENT_REF=v2026.5.29
# SHA 為防 tag 被上游移動的二次保險（與 .github/workflows/tests.yml 的 HERMES_AGENT_SHA 同值）。
# ⚠ 升級版本鎖時三處要一起改：CI workflow（REF/SHA）/ 本檔（REF/SHA）/ ci/requirements-test.txt。
ARG HERMES_AGENT_SHA=e71a2bd11b733f3be7cf99deafde0066c343d462

ENV HERMES_HOME=/root/.hermes \
    PATH="/root/.local/bin:${PATH}" \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ripgrep rsync ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

# ── ① base：鎖定版本的 hermes，巢狀安裝在 $HERMES_HOME/hermes-agent ──────────
# checkout 後比對實際 HEAD == 鎖定 SHA（對齊 CI），不符即硬失敗，避免 tag 被移動時靜默吃到不同 commit。
RUN git clone "${HERMES_AGENT_REPO}" "${HERMES_HOME}/hermes-agent" \
 && git -C "${HERMES_HOME}/hermes-agent" checkout "${HERMES_AGENT_REF}" \
 && got="$(git -C "${HERMES_HOME}/hermes-agent" rev-parse HEAD)" \
 && if [ "${got}" != "${HERMES_AGENT_SHA}" ]; then \
        echo "ERROR: hermes-agent HEAD ${got} != 鎖定 SHA ${HERMES_AGENT_SHA}（tag 被移動？）" >&2; \
        exit 1; \
    fi \
 && git -C "${HERMES_HOME}/hermes-agent" rev-parse HEAD > "${HERMES_HOME}/.hermes-agent-pinned-sha"
# setup-hermes.sh：建 venv + uv pip install -e ".[all]"(195 套件) + 同步 74 bundled skills
RUN cd "${HERMES_HOME}/hermes-agent" \
 && yes n | env HERMES_HOME="${HERMES_HOME}" bash setup-hermes.sh

# ── ② 疊上 A：我的調校（hermit repo 鏡像）────────────────────────────────
# .dockerignore 已排除本地 hermes-agent/、.hermes/（避免把 venv/secrets/狀態烤進來）
COPY . /opt/hermit/
# 從 repo 鏡像還原到 $HERMES_HOME：overlay→~/.hermes、patches/files→hermes-agent、diffs→git apply
RUN cd /opt/hermit && bash scripts/sync_overlays.sh import

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
