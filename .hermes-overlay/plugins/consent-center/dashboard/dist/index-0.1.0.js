/**
 * Consent Center Plugin (Stage C)
 *
 * 兩個 panel：
 *   1. 待確認提議（GET /proposals）：列舉 connector 經 propose tool 寫入待確認區的候選項。
 *      點開展開 fetch GET /proposals/{id}，逐 item 渲染 checkbox（預設依 item.selected_default），
 *      顯示 content / target / 頂層 source 的 Badge。勾選後 POST /proposals/{id}/confirm
 *      （body { selected_item_ids: [...] }）寫入受管記憶，或 POST /proposals/{id}/cancel 丟棄。
 *   2. 確認歷史（GET /history）：列舉 confirm_*.json audit。點開 fetch GET /history/{filename}，
 *      顯示 written / written_at。
 *
 * 紅線#5：寫入受管記憶的唯一入口是 confirm endpoint（後端同步呼叫 apply_proposal）。
 * 前端只負責提案展示與「人工確認」勾選；不直接觸碰任何記憶檔。
 *
 * Plain IIFE，靠 window.__HERMES_PLUGIN_SDK__ 取得 React 與 shadcn 元件。
 * SDK 沒有 Checkbox / toast，用 raw input + 顯示橫幅替代。
 * Tailwind JIT 不掃 .hermes/plugins/，arbitrary 值改 inline style。
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React, useI18n } = SDK;
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button } = SDK.components;
  const { useState, useEffect, useMemo, useCallback } = SDK.hooks;

  const API_BASE = "/api/plugins/consent-center";
  const PLUGIN_NAME = "consent-center";

  // Panel accent colors — 視覺區分 pending（待確認）vs history（已確認）
  const ACCENT_PENDING = "rgb(234 179 8)";   // amber
  const ACCENT_HISTORY = "rgb(34 197 94)";   // green

  // ─────────────────────────────────────────────────────────────────────
  // i18n（中文為主、英文為輔）
  // ─────────────────────────────────────────────────────────────────────
  const STRINGS = {
    zh: {
      title: "權限同意中心",
      pendingHeader: "待確認提議",
      pendingSubtitle: "machine proposes / human confirms — 確認後才會寫入個人記憶",
      historyHeader: "確認歷史",
      historySubtitle: "已寫入受管記憶的紀錄（唯讀）",
      noProposals: "目前沒有等待確認的提議",
      noProposalsHint: "Connector 經 propose tool 把候選項寫入待確認區後，會出現在此。下方「確認歷史」是過去已寫入的紀錄，不是待確認。",
      noHistory: "尚無確認紀錄。",
      loading: "載入中…",
      itemCount: "項目",
      noItemsInProposal: "（此提議無項目）",
      labelTarget: "目標",
      labelSource: "來源",
      btnConfirm: "確認寫入",
      btnCancel: "取消提議",
      btnConfirming: "寫入中…",
      btnCancelling: "取消中…",
      btnExpand: "展開",
      btnCollapse: "收起",
      successConfirm: "已寫入：",
      successCancel: "已取消提議：",
      errLoadList: "載入待確認提議失敗：",
      errLoadDetail: "載入提議詳細失敗：",
      errConfirm: "寫入失敗：",
      errCancel: "取消失敗：",
      errLoadHistory: "載入歷史失敗：",
      labelWritten: "寫入項目：",
      labelWrittenAt: "寫入時間：",
      labelSelected: "已勾選：",
      noneSelected: "（未勾選任何項目）",
    },
  };

  function useT() {
    const i18n = useI18n ? useI18n() : { locale: "zh" };
    const dict = STRINGS[i18n.locale] || STRINGS.zh;
    return function t(k) { return dict[k] != null ? dict[k] : k; };
  }

  // ─────────────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────────────
  function fetchJSON(path, init) {
    return SDK.fetchJSON(path, init);
  }

  function postJSON(path, body) {
    return SDK.fetchJSON(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  function errMsg(err) {
    if (!err) return "";
    if (err.message) return err.message;
    return String(err);
  }

  function fmtTime(s) {
    if (!s) return "";
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleString();
  }

  // ─────────────────────────────────────────────────────────────────────
  // ProposalRow — 單一提議的列 + 展開後逐 item 勾選
  // ─────────────────────────────────────────────────────────────────────
  function ProposalRow(props) {
    const { proposal, expanded, onToggle } = props;
    const t = useT();
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState({}); // {item_id: bool}
    const [actionStatus, setActionStatus] = useState(null); // {kind:"ok"|"err", msg}
    const [busy, setBusy] = useState(null); // "confirm" | "cancel" | null

    // Fetch detail when expanded for first time.
    useEffect(function () {
      if (!expanded || detail) return;
      setLoading(true);
      setError(null);
      fetchJSON(API_BASE + "/proposals/" + encodeURIComponent(proposal.proposal_id))
        .then(function (data) {
          setDetail(data);
          // 預設勾選依 item.selected_default（缺值視為 true）
          const init = {};
          ((data && data.items) || []).forEach(function (it, i) {
            const id = it.id || ("item-" + (i + 1));
            init[id] = it.selected_default !== false;
          });
          setSelected(init);
        })
        .catch(function (err) { setError(t("errLoadDetail") + errMsg(err)); })
        .finally(function () { setLoading(false); });
    }, [expanded, proposal.proposal_id]);

    const items = (detail && detail.items) || [];
    const source = (detail && detail.source) || proposal.source || "";

    function itemId(it, i) {
      return it.id || ("item-" + (i + 1));
    }

    function toggle(id) {
      setSelected(function (prev) {
        const next = Object.assign({}, prev);
        next[id] = !prev[id];
        return next;
      });
    }

    function pickedIds() {
      return items
        .map(function (it, i) { return itemId(it, i); })
        .filter(function (id) { return selected[id]; });
    }

    function doConfirm() {
      const picked = pickedIds();
      setBusy("confirm");
      setActionStatus(null);
      postJSON(API_BASE + "/proposals/" + encodeURIComponent(proposal.proposal_id) + "/confirm", {
        selected_item_ids: picked,
      })
        .then(function (data) {
          const written = (data && data.written) || [];
          setActionStatus({ kind: "ok", msg: t("successConfirm") + (written.join("、") || "—") });
          if (props.onChanged) props.onChanged();
        })
        .catch(function (err) { setActionStatus({ kind: "err", msg: t("errConfirm") + errMsg(err) }); })
        .finally(function () { setBusy(null); });
    }

    function doCancel() {
      setBusy("cancel");
      setActionStatus(null);
      postJSON(API_BASE + "/proposals/" + encodeURIComponent(proposal.proposal_id) + "/cancel", {})
        .then(function () {
          setActionStatus({ kind: "ok", msg: t("successCancel") + proposal.proposal_id });
          if (props.onChanged) props.onChanged();
        })
        .catch(function (err) { setActionStatus({ kind: "err", msg: t("errCancel") + errMsg(err) }); })
        .finally(function () { setBusy(null); });
    }

    const summary = proposal.summary || {};
    const header = React.createElement("div", { className: "flex items-center gap-2 flex-wrap" },
      React.createElement("span", { className: "text-xs text-muted-foreground" }, fmtTime(proposal.created_at)),
      React.createElement("span", { className: "text-xs font-medium break-all" }, proposal.proposal_id),
      React.createElement(Badge, { variant: "outline" }, t("itemCount") + ":" + (summary.item_count || 0)),
      proposal.status && React.createElement(Badge, { variant: "outline" }, proposal.status),
      React.createElement(Badge, { variant: "secondary" }, t("labelSource") + ":" + (proposal.source || "")),
    );

    return React.createElement(Card, { className: "mb-2" },
      React.createElement(CardHeader, null,
        React.createElement("div", {
          className: "flex items-center cursor-pointer",
          onClick: onToggle,
        },
          React.createElement(CardTitle, { className: "text-sm flex-1 min-w-0" }, header),
          React.createElement(Button, {
            onClick: function (e) { e.stopPropagation(); onToggle(); },
            className: "text-xs px-2 py-1",
          }, expanded ? t("btnCollapse") : t("btnExpand")),
        ),
      ),
      expanded && React.createElement(CardContent, { className: "pt-0" },
        loading && React.createElement("p", { className: "text-sm text-muted-foreground" }, t("loading")),
        error && React.createElement("p", {
          className: "text-sm",
          style: { color: "rgb(239 68 68)" },
        }, error),
        detail && React.createElement(React.Fragment, null,
          React.createElement("div", { className: "flex flex-col gap-2 mb-3" },
            items.length === 0
              ? React.createElement("p", { className: "text-sm text-muted-foreground" }, t("noItemsInProposal"))
              : items.map(function (it, i) {
                const id = itemId(it, i);
                const checked = !!selected[id];
                return React.createElement("div", {
                  key: id,
                  className: "border border-border p-2 text-sm",
                },
                  React.createElement("label", {
                    className: "flex items-start gap-2 cursor-pointer",
                  },
                    React.createElement("input", {
                      type: "checkbox",
                      checked: checked,
                      onChange: function () { toggle(id); },
                      style: { cursor: "pointer", marginTop: 3, flex: "none" },
                    }),
                    React.createElement("div", { className: "flex flex-col gap-1 min-w-0" },
                      React.createElement("span", { className: "break-all" }, it.content || ""),
                      React.createElement("div", { className: "flex items-center gap-1 flex-wrap" },
                        React.createElement(Badge, { variant: "outline" }, t("labelTarget") + ":" + (it.target || "memory")),
                        it.kind && React.createElement(Badge, { variant: "outline" }, it.kind),
                        React.createElement(Badge, { variant: "secondary" }, t("labelSource") + ":" + source),
                        React.createElement("span", { className: "text-xs text-muted-foreground" }, id),
                      ),
                    ),
                  ),
                );
              }),
          ),
          React.createElement("div", { className: "flex items-center gap-3 mb-2" },
            React.createElement(Button, {
              onClick: doConfirm,
              disabled: busy === "confirm",
              className: "ml-auto",
            }, busy === "confirm" ? t("btnConfirming") : t("btnConfirm")),
            React.createElement(Button, {
              onClick: doCancel,
              disabled: busy === "cancel",
            }, busy === "cancel" ? t("btnCancelling") : t("btnCancel")),
          ),
          actionStatus && React.createElement("p", {
            className: "text-sm",
            style: {
              color: actionStatus.kind === "ok" ? "rgb(34 197 94)" : "rgb(239 68 68)",
              wordBreak: "break-all",
            },
          }, actionStatus.msg),
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────
  // HistoryRow — 單筆 confirm audit
  // ─────────────────────────────────────────────────────────────────────
  function HistoryRow(props) {
    const { item } = props;
    const t = useT();
    const [open, setOpen] = useState(false);
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    function toggle() {
      const willOpen = !open;
      setOpen(willOpen);
      if (willOpen && !detail) {
        setLoading(true);
        setError(null);
        fetchJSON(API_BASE + "/history/" + encodeURIComponent(item.filename))
          .then(setDetail)
          .catch(function (err) { setError(t("errLoadHistory") + errMsg(err)); })
          .finally(function () { setLoading(false); });
      }
    }

    const counts = item.counts || {};
    const written = (detail && detail.written) || [];

    return React.createElement(Card, { className: "mb-2" },
      React.createElement(CardHeader, {
        className: "cursor-pointer",
        onClick: toggle,
      },
        React.createElement(CardTitle, { className: "text-sm flex items-center gap-2 flex-wrap" },
          React.createElement("span", null, t("labelWrittenAt") + (fmtTime(item.written_at) || item.filename)),
          React.createElement(Badge, { variant: "outline" }, t("labelWritten") + (counts.written || 0)),
          React.createElement(Button, {
            onClick: function (e) { e.stopPropagation(); toggle(); },
            className: "ml-auto text-xs px-2 py-1",
          }, open ? t("btnCollapse") : t("btnExpand")),
        ),
      ),
      open && React.createElement(CardContent, { className: "pt-0" },
        loading && React.createElement("p", { className: "text-sm text-muted-foreground" }, t("loading")),
        error && React.createElement("p", {
          className: "text-sm",
          style: { color: "rgb(239 68 68)" },
        }, error),
        detail && React.createElement("div", { className: "flex flex-col gap-2 text-sm" },
          React.createElement("div", { className: "text-xs text-muted-foreground" },
            t("labelWrittenAt") + fmtTime(detail.written_at)),
          written.length === 0
            ? React.createElement("p", { className: "text-sm text-muted-foreground" }, t("noneSelected"))
            : written.map(function (w, i) {
              return React.createElement("div", {
                key: (w && w.id) || ("w" + i),
                className: "border border-border p-2",
                style: { borderLeft: "3px solid " + ACCENT_HISTORY },
              },
                React.createElement("div", { className: "break-all" }, (w && w.content) || ""),
                React.createElement("div", { className: "flex items-center gap-1 flex-wrap mt-1" },
                  React.createElement(Badge, { variant: "outline" }, t("labelTarget") + ":" + ((w && w.target) || "")),
                  React.createElement("span", { className: "text-xs text-muted-foreground" }, (w && w.id) || ""),
                ),
              );
            }),
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────
  // Main page
  // ─────────────────────────────────────────────────────────────────────
  function ConsentCenterPage() {
    const t = useT();
    const [proposals, setProposals] = useState([]);
    const [propLoading, setPropLoading] = useState(true);
    const [propError, setPropError] = useState(null);
    const [expandedId, setExpandedId] = useState(null);

    const [history, setHistory] = useState([]);
    const [histLoading, setHistLoading] = useState(true);
    const [histError, setHistError] = useState(null);

    const refreshProposals = useCallback(function () {
      setPropLoading(true);
      setPropError(null);
      return fetchJSON(API_BASE + "/proposals")
        .then(function (data) {
          setProposals(Array.isArray(data.proposals) ? data.proposals : []);
        })
        .catch(function (err) {
          setPropError(t("errLoadList") + errMsg(err));
        })
        .finally(function () { setPropLoading(false); });
    }, []);

    const refreshHistory = useCallback(function () {
      setHistLoading(true);
      setHistError(null);
      return fetchJSON(API_BASE + "/history?limit=50")
        .then(function (data) {
          setHistory(Array.isArray(data.history) ? data.history : []);
        })
        .catch(function (err) {
          setHistError(t("errLoadHistory") + errMsg(err));
        })
        .finally(function () { setHistLoading(false); });
    }, []);

    useEffect(function () {
      refreshProposals();
      refreshHistory();
    }, [refreshProposals, refreshHistory]);

    function onChanged() {
      // 一筆提議被確認或取消 — 雙 panel 都刷新
      refreshProposals();
      refreshHistory();
      setExpandedId(null);
    }

    function toggle(id) {
      setExpandedId(function (prev) { return prev === id ? null : id; });
    }

    return React.createElement("div", {
      className: "flex flex-col gap-3",
      style: { padding: "1rem" },
    },
      React.createElement("div", { className: "flex items-center gap-3" },
        React.createElement("h2", { className: "text-base font-medium" }, t("title")),
        React.createElement(Badge, { variant: "outline" }, "v0.1.0"),
      ),
      // Pending proposals
      React.createElement(Card, { style: { borderLeft: "4px solid " + ACCENT_PENDING } },
        React.createElement(CardHeader, null,
          React.createElement("div", { className: "flex items-center gap-2" },
            React.createElement("span", {
              style: {
                width: 10, height: 10, borderRadius: "50%",
                backgroundColor: ACCENT_PENDING, display: "inline-block", flex: "none",
              },
            }),
            React.createElement(CardTitle, { className: "text-base" },
              t("pendingHeader") + " (" + proposals.length + ")"),
          ),
          React.createElement("p", {
            className: "text-xs text-muted-foreground",
            style: { marginTop: 4 },
          }, t("pendingSubtitle")),
        ),
        React.createElement(CardContent, null,
          propLoading && React.createElement("p", { className: "text-sm text-muted-foreground" }, t("loading")),
          propError && React.createElement("p", {
            className: "text-sm",
            style: { color: "rgb(239 68 68)" },
          }, propError),
          !propLoading && !propError && proposals.length === 0 &&
            React.createElement("div", {
              style: {
                border: "1px dashed rgb(234 179 8 / 0.4)",
                borderRadius: 6,
                padding: "1rem",
                backgroundColor: "rgb(234 179 8 / 0.05)",
              },
            },
              React.createElement("p", {
                className: "text-sm font-medium",
                style: { color: ACCENT_PENDING },
              }, t("noProposals")),
              React.createElement("p", {
                className: "text-xs text-muted-foreground",
                style: { marginTop: 4 },
              }, t("noProposalsHint")),
            ),
          proposals.map(function (p) {
            return React.createElement(ProposalRow, {
              key: p.proposal_id,
              proposal: p,
              expanded: expandedId === p.proposal_id,
              onToggle: function () { toggle(p.proposal_id); },
              onChanged: onChanged,
            });
          }),
        ),
      ),
      // History
      React.createElement(Card, { style: { borderLeft: "4px solid " + ACCENT_HISTORY } },
        React.createElement(CardHeader, null,
          React.createElement("div", { className: "flex items-center gap-2" },
            React.createElement("span", {
              style: {
                width: 10, height: 10, borderRadius: "50%",
                backgroundColor: ACCENT_HISTORY, display: "inline-block", flex: "none",
              },
            }),
            React.createElement(CardTitle, { className: "text-base" },
              t("historyHeader") + " (" + history.length + ")"),
          ),
          React.createElement("p", {
            className: "text-xs text-muted-foreground",
            style: { marginTop: 4 },
          }, t("historySubtitle")),
        ),
        React.createElement(CardContent, null,
          histLoading && React.createElement("p", { className: "text-sm text-muted-foreground" }, t("loading")),
          histError && React.createElement("p", {
            className: "text-sm",
            style: { color: "rgb(239 68 68)" },
          }, histError),
          !histLoading && !histError && history.length === 0 &&
            React.createElement("p", { className: "text-sm text-muted-foreground" }, t("noHistory")),
          history.map(function (h) {
            return React.createElement(HistoryRow, { key: h.filename, item: h });
          }),
        ),
      ),
    );
  }

  // 沿用既有 plugin 的 register 簽章（傳 plugin name + component）
  window.__HERMES_PLUGINS__.register(PLUGIN_NAME, ConsentCenterPage);
})();
