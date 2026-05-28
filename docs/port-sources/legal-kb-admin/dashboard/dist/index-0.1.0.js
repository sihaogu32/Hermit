/**
 * Legal KB Admin Plugin (Stage C)
 *
 * 兩個 panel：
 *   1. 待確認 scan：列舉 /scans，點開展開三欄（new / changed / obsolete），
 *      changed 法規可再展開看 article-level diff，勾選後 POST confirm 或 cancel。
 *   2. 執行歷史：列舉 /history，點開展開 changelog 與 article_diffs。
 *
 * URL ?scan_id=xxx 自動展開該 scan 並 fetch 詳細內容。
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
  const { cn } = SDK.utils;

  const API_BASE = "/api/plugins/legal-kb-admin";
  const PLUGIN_NAME = "legal-kb-admin";

  // Panel accent colors — 視覺區分 pending（待動作）vs history（已完成）
  const ACCENT_PENDING = "rgb(234 179 8)";   // amber
  const ACCENT_HISTORY = "rgb(34 197 94)";   // green

  // ─────────────────────────────────────────────────────────────────────
  // i18n（中文為主、英文為輔）
  // ─────────────────────────────────────────────────────────────────────
  const STRINGS = {
    zh: {
      title: "法規 KB 管理",
      pendingHeader: "待確認 scan",
      pendingSubtitle: "等候人工確認 — 套用後才會修改 KB",
      historyHeader: "執行歷史",
      historySubtitle: "已套用至 KB 的紀錄（唯讀，不會再修改 KB）",
      noScans: "目前沒有等待確認的 scan",
      noScansHint: "由 hermes cron 排程觸發 RunDownloadAndScan 後，pending scan 會出現在此。下方「執行歷史」是過去已套用的紀錄，不是 pending。",
      noHistory: "尚無 apply 紀錄。",
      loading: "載入中…",
      countNew: "新增",
      countChanged: "更新",
      countObsolete: "下架",
      colNew: "新增法規",
      colChanged: "更新法規",
      colObsolete: "下架法規",
      noLawsInColumn: "（無）",
      labelDeleteObsolete: "同時刪除 obsolete 法規目錄",
      btnApply: "套用選定",
      btnCancel: "取消此 scan",
      btnApplying: "套用中…",
      btnCancelling: "取消中…",
      btnExpand: "展開",
      btnCollapse: "收起",
      successApply: "已套用：",
      successCancel: "已取消 scan：",
      errLoadList: "載入待確認 scan 失敗：",
      errLoadDetail: "載入 scan 詳細失敗：",
      errApply: "套用失敗：",
      errCancel: "取消失敗：",
      errLoadHistory: "載入歷史失敗：",
      labelArticleDiff: "條文差異",
      diffAdded: "新增條文",
      diffRemoved: "刪除條文",
      diffModified: "修改條文",
      diffNoChange: "（此 scan 未含 article-level diff）",
      labelOldContent: "舊內容",
      labelNewContent: "新內容",
      labelSourceUsed: "來源：",
      labelTimestamp: "時間：",
      labelChangelog: "Changelog 路徑：",
      labelWritten: "寫入：",
      labelDeleted: "刪除：",
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

  function getQueryScanId() {
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get("scan_id");
    } catch (_e) {
      return null;
    }
  }

  function errMsg(err) {
    if (!err) return "";
    if (err.message) return err.message;
    return String(err);
  }

  function fmtTime(s) {
    if (!s) return "";
    // try ISO; fallback to as-is
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleString();
  }

  // ─────────────────────────────────────────────────────────────────────
  // ArticleDiffView — 渲染 changed 法規的 article-level diff
  // ─────────────────────────────────────────────────────────────────────
  function ArticleDiffView(props) {
    const { diff } = props;
    const t = useT();
    if (!diff) return React.createElement("p", { className: "text-xs text-muted-foreground" }, t("diffNoChange"));
    const added = diff.added || [];
    const removed = diff.removed || [];
    const modified = diff.modified || [];
    if (!added.length && !removed.length && !modified.length) {
      return React.createElement("p", { className: "text-xs text-muted-foreground" }, t("diffNoChange"));
    }
    return React.createElement("div", { className: "flex flex-col gap-2 text-xs" },
      added.length > 0 && React.createElement("div", null,
        React.createElement("div", { className: "font-medium" }, t("diffAdded") + " (" + added.length + ")"),
        added.map(function (a, i) {
          return React.createElement("div", {
            key: "a" + i,
            className: "border border-border p-1 mt-1",
            style: { borderLeft: "3px solid rgb(34 197 94)" },
          },
            React.createElement("div", { className: "font-medium" }, a.no),
            React.createElement("pre", {
              className: "whitespace-pre-wrap break-all leading-relaxed",
            }, a.content || ""),
          );
        }),
      ),
      removed.length > 0 && React.createElement("div", null,
        React.createElement("div", { className: "font-medium" }, t("diffRemoved") + " (" + removed.length + ")"),
        removed.map(function (a, i) {
          return React.createElement("div", {
            key: "r" + i,
            className: "border border-border p-1 mt-1",
            style: { borderLeft: "3px solid rgb(239 68 68)" },
          },
            React.createElement("div", { className: "font-medium" }, a.no),
            React.createElement("pre", {
              className: "whitespace-pre-wrap break-all leading-relaxed",
            }, a.content || ""),
          );
        }),
      ),
      modified.length > 0 && React.createElement("div", null,
        React.createElement("div", { className: "font-medium" }, t("diffModified") + " (" + modified.length + ")"),
        modified.map(function (a, i) {
          return React.createElement("div", {
            key: "m" + i,
            className: "border border-border p-1 mt-1",
            style: { borderLeft: "3px solid rgb(234 179 8)" },
          },
            React.createElement("div", { className: "font-medium" }, a.no),
            React.createElement("div", { className: "text-muted-foreground mt-1" }, t("labelOldContent")),
            React.createElement("pre", {
              className: "whitespace-pre-wrap break-all leading-relaxed",
              style: { backgroundColor: "rgba(239, 68, 68, 0.08)" },
            }, a.old_content || ""),
            React.createElement("div", { className: "text-muted-foreground mt-1" }, t("labelNewContent")),
            React.createElement("pre", {
              className: "whitespace-pre-wrap break-all leading-relaxed",
              style: { backgroundColor: "rgba(34, 197, 94, 0.08)" },
            }, a.new_content || ""),
          );
        }),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────
  // ScanRow — 單一 scan 的列 + 展開後的法規勾選
  // ─────────────────────────────────────────────────────────────────────
  function ScanRow(props) {
    const { scan, expanded, onToggle, autoExpand } = props;
    const t = useT();
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState({}); // {law_name: bool}
    const [deleteObsolete, setDeleteObsolete] = useState(false);
    const [actionStatus, setActionStatus] = useState(null); // {kind:"ok"|"err", msg:string}
    const [busy, setBusy] = useState(null); // "apply" | "cancel" | null
    const [diffOpen, setDiffOpen] = useState({}); // {law_name: bool}

    // Fetch detail when expanded for first time (or when autoExpand triggers).
    useEffect(function () {
      if (!expanded || detail) return;
      setLoading(true);
      setError(null);
      fetchJSON(API_BASE + "/scans/" + encodeURIComponent(scan.scan_id))
        .then(function (data) {
          setDetail(data);
          // default-check all laws in new/changed/obsolete
          const init = {};
          const inner = (data && data.scan) || {};
          (inner.new || []).forEach(function (n) { init[n] = true; });
          (inner.changed || []).forEach(function (n) { init[n] = true; });
          (inner.obsolete || []).forEach(function (n) { init[n] = true; });
          setSelected(init);
        })
        .catch(function (err) { setError(t("errLoadDetail") + errMsg(err)); })
        .finally(function () { setLoading(false); });
    }, [expanded, scan.scan_id]);

    useEffect(function () {
      if (autoExpand && !expanded) onToggle();
    }, [autoExpand]);

    const innerScan = (detail && detail.scan) || {};
    const newLaws = innerScan.new || [];
    const changedLaws = innerScan.changed || [];
    const obsoleteLaws = innerScan.obsolete || [];
    const articleDiffs = innerScan.article_diffs || {};

    function toggle(name) {
      setSelected(function (prev) {
        const next = Object.assign({}, prev);
        next[name] = !prev[name];
        return next;
      });
    }
    function toggleDiff(name) {
      setDiffOpen(function (prev) {
        const next = Object.assign({}, prev);
        next[name] = !prev[name];
        return next;
      });
    }

    function pickedLaws() {
      const all = [].concat(newLaws, changedLaws, obsoleteLaws);
      return all.filter(function (n) { return selected[n]; });
    }

    function doApply() {
      const picked = pickedLaws();
      setBusy("apply");
      setActionStatus(null);
      postJSON(API_BASE + "/scans/" + encodeURIComponent(scan.scan_id) + "/confirm", {
        laws: picked,
        delete_obsolete: deleteObsolete,
      })
        .then(function (data) {
          const written = (data.applied && data.applied.written) || [];
          setActionStatus({ kind: "ok", msg: t("successApply") + written.join("、") });
          if (props.onChanged) props.onChanged();
        })
        .catch(function (err) { setActionStatus({ kind: "err", msg: t("errApply") + errMsg(err) }); })
        .finally(function () { setBusy(null); });
    }

    function doCancel() {
      setBusy("cancel");
      setActionStatus(null);
      postJSON(API_BASE + "/scans/" + encodeURIComponent(scan.scan_id) + "/cancel", {})
        .then(function () {
          setActionStatus({ kind: "ok", msg: t("successCancel") + scan.scan_id });
          if (props.onChanged) props.onChanged();
        })
        .catch(function (err) { setActionStatus({ kind: "err", msg: t("errCancel") + errMsg(err) }); })
        .finally(function () { setBusy(null); });
    }

    const summary = scan.summary || {};
    const header = React.createElement("div", { className: "flex items-center gap-2 flex-wrap" },
      React.createElement("span", { className: "text-xs text-muted-foreground" }, fmtTime(scan.created_at)),
      React.createElement("span", { className: "text-xs font-medium" }, scan.scan_id),
      React.createElement(Badge, { variant: "outline" }, t("countNew") + ":" + (summary.new || 0)),
      React.createElement(Badge, { variant: "outline" }, t("countChanged") + ":" + (summary.changed || 0)),
      React.createElement(Badge, { variant: "outline" }, t("countObsolete") + ":" + (summary.obsolete || 0)),
      React.createElement("span", { className: "text-xs text-muted-foreground ml-auto" },
        t("labelSourceUsed") + (scan.source_used || "")),
    );

    function renderColumn(title, items, allowDiff) {
      return React.createElement("div", { className: "flex-1 min-w-0" },
        React.createElement("div", { className: "text-xs font-medium mb-1" }, title + " (" + items.length + ")"),
        items.length === 0
          ? React.createElement("p", { className: "text-xs text-muted-foreground" }, t("noLawsInColumn"))
          : items.map(function (n) {
            const checked = !!selected[n];
            const hasDiff = allowDiff && articleDiffs[n];
            const open = !!diffOpen[n];
            return React.createElement("div", {
              key: n,
              className: "border border-border p-1 mb-1 text-sm",
            },
              React.createElement("div", { className: "flex items-center gap-2" },
                React.createElement("input", {
                  type: "checkbox",
                  checked: checked,
                  onChange: function () { toggle(n); },
                  style: { cursor: "pointer" },
                }),
                React.createElement("span", { className: "break-all" }, n),
                hasDiff && React.createElement(Button, {
                  onClick: function () { toggleDiff(n); },
                  className: "ml-auto text-xs px-2 py-0",
                }, open ? t("btnCollapse") : (t("labelArticleDiff") + " " +
                  ((articleDiffs[n].added || []).length + (articleDiffs[n].removed || []).length +
                    (articleDiffs[n].modified || []).length))),
              ),
              hasDiff && open && React.createElement("div", { className: "mt-2 pl-6" },
                React.createElement(ArticleDiffView, { diff: articleDiffs[n] })),
            );
          }),
      );
    }

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
          React.createElement("div", { className: "flex gap-3 mb-3" },
            renderColumn(t("colNew"), newLaws, false),
            renderColumn(t("colChanged"), changedLaws, true),
            renderColumn(t("colObsolete"), obsoleteLaws, false),
          ),
          React.createElement("div", { className: "flex items-center gap-3 mb-2" },
            React.createElement("label", {
              className: "flex items-center gap-2 text-sm cursor-pointer",
            },
              React.createElement("input", {
                type: "checkbox",
                checked: deleteObsolete,
                onChange: function (e) { setDeleteObsolete(e.target.checked); },
              }),
              t("labelDeleteObsolete"),
            ),
            React.createElement(Button, {
              onClick: doApply,
              disabled: busy === "apply",
              className: "ml-auto",
            }, busy === "apply" ? t("btnApplying") : t("btnApply")),
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
  // HistoryRow — 單筆 changelog
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
    const articleDiffs = (detail && detail.article_diffs) || {};

    return React.createElement(Card, { className: "mb-2" },
      React.createElement(CardHeader, {
        className: "cursor-pointer",
        onClick: toggle,
      },
        React.createElement(CardTitle, { className: "text-sm flex items-center gap-2 flex-wrap" },
          React.createElement("span", null, t("labelTimestamp") + (item.timestamp_utc || item.filename)),
          React.createElement(Badge, { variant: "outline" }, t("countNew") + ":" + (counts.new || 0)),
          React.createElement(Badge, { variant: "outline" }, t("countChanged") + ":" + (counts.changed || 0)),
          React.createElement(Badge, { variant: "outline" }, t("countObsolete") + ":" + (counts.obsolete || 0)),
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
          React.createElement("div", null, t("labelWritten") + ((detail.written || []).join("、") || "—")),
          React.createElement("div", null, t("labelDeleted") + ((detail.deleted || []).join("、") || "—")),
          Object.keys(articleDiffs).length === 0
            ? React.createElement("p", { className: "text-xs text-muted-foreground" }, t("diffNoChange"))
            : Object.keys(articleDiffs).sort().map(function (name) {
              return React.createElement("div", {
                key: name,
                className: "border border-border p-2",
              },
                React.createElement("div", { className: "font-medium mb-1" }, name),
                React.createElement(ArticleDiffView, { diff: articleDiffs[name] }),
              );
            }),
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────────
  // Main page
  // ─────────────────────────────────────────────────────────────────────
  function LegalKBAdminPage() {
    const t = useT();
    const [scans, setScans] = useState([]);
    const [scansLoading, setScansLoading] = useState(true);
    const [scansError, setScansError] = useState(null);
    const [expandedId, setExpandedId] = useState(null);

    const [history, setHistory] = useState([]);
    const [histLoading, setHistLoading] = useState(true);
    const [histError, setHistError] = useState(null);

    const queryScanId = useMemo(getQueryScanId, []);

    const refreshScans = useCallback(function () {
      setScansLoading(true);
      setScansError(null);
      return fetchJSON(API_BASE + "/scans")
        .then(function (data) {
          setScans(Array.isArray(data.scans) ? data.scans : []);
        })
        .catch(function (err) {
          setScansError(t("errLoadList") + errMsg(err));
        })
        .finally(function () { setScansLoading(false); });
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
      refreshScans();
      refreshHistory();
    }, [refreshScans, refreshHistory]);

    // auto-expand based on URL
    useEffect(function () {
      if (queryScanId && !expandedId) {
        setExpandedId(queryScanId);
      }
    }, [queryScanId]);

    function onChanged() {
      // a scan got applied or cancelled — both lists refresh
      refreshScans();
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
      // Pending scans
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
              t("pendingHeader") + " (" + scans.length + ")"),
          ),
          React.createElement("p", {
            className: "text-xs text-muted-foreground",
            style: { marginTop: 4 },
          }, t("pendingSubtitle")),
        ),
        React.createElement(CardContent, null,
          scansLoading && React.createElement("p", { className: "text-sm text-muted-foreground" }, t("loading")),
          scansError && React.createElement("p", {
            className: "text-sm",
            style: { color: "rgb(239 68 68)" },
          }, scansError),
          !scansLoading && !scansError && scans.length === 0 &&
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
              }, t("noScans")),
              React.createElement("p", {
                className: "text-xs text-muted-foreground",
                style: { marginTop: 4 },
              }, t("noScansHint")),
            ),
          scans.map(function (s) {
            return React.createElement(ScanRow, {
              key: s.scan_id,
              scan: s,
              expanded: expandedId === s.scan_id,
              onToggle: function () { toggle(s.scan_id); },
              autoExpand: queryScanId === s.scan_id,
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
  window.__HERMES_PLUGINS__.register(PLUGIN_NAME, LegalKBAdminPage);
})();
