/**
 * Calendar Plugin (v0.1.0)
 *
 * 合併視圖（GET /events）：native（hermit 擁有）＋ ICS 訂閱快取（下一段）＋ 選配 google。
 * 每筆事件標 source。原生事件（source=native）可在此手動增刪改（呼叫 calendar_store，
 * 使用者操作＝本人即時的人工確認）；外部來源（google/ics）為唯讀鏡像，不提供增刪改。
 * agent 想加事件一律走 propose_event → consent-center 確認，不在此繞過。
 *
 * 三種檢視：列表 / 月 / 週。底部為 ICS 訂閱管理（貼 / 刪 URL、手動 refresh）；
 * refresh 目前回 deferred（ICS 解析需 icalendar，下一段接上）。
 *
 * Plain IIFE，靠 window.__HERMES_PLUGIN_SDK__ 取得 React 與 shadcn 元件（同 consent-center）。
 * Tailwind JIT 不掃 .hermes/plugins/，arbitrary 值改 inline style。
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React, useI18n } = SDK;
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button } = SDK.components;
  const { useState, useEffect, useMemo, useCallback } = SDK.hooks;
  const h = React.createElement;

  const API_BASE = "/api/plugins/calendar";
  const PLUGIN_NAME = "calendar";

  const ACCENT = "rgb(59 130 246)";        // blue — calendar
  const ACCENT_SUB = "rgb(168 85 247)";    // purple — subscriptions
  const SOURCE_COLOR = {
    native: "rgb(59 130 246)",
    google: "rgb(34 197 94)",
    ics: "rgb(234 179 8)",
  };
  const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

  // ── i18n ────────────────────────────────────────────────────────────────
  const STRINGS = {
    zh: {
      title: "行事曆",
      viewList: "列表", viewMonth: "月", viewWeek: "週",
      prev: "‹", next: "›", today: "今天",
      newEvent: "新增事件",
      noEvents: "這段期間沒有事件。",
      loading: "載入中…",
      fTitle: "標題", fStart: "開始", fEnd: "結束", fAllDay: "整天",
      fLocation: "地點", fDescription: "說明",
      save: "儲存", saving: "儲存中…", cancel: "取消",
      edit: "編輯", del: "刪除", deleting: "刪除中…",
      readonlyHint: "外部來源（唯讀鏡像），不可在此編輯",
      errLoad: "載入事件失敗：", errSave: "儲存失敗：", errDelete: "刪除失敗：",
      subsHeader: "ICS 訂閱", subsSubtitle: "貼上 Google 設定裡的私人 iCal 網址（唯讀匯入）",
      subUrl: "iCal 網址", subLabel: "標籤（選填）",
      addSub: "新增訂閱", refresh: "重新抓取", refreshing: "抓取中…",
      noSubs: "尚無 ICS 訂閱。", errSub: "訂閱操作失敗：",
      sourceLabel: "來源",
    },
  };
  function useT() {
    const i18n = useI18n ? useI18n() : { locale: "zh" };
    const dict = STRINGS[i18n.locale] || STRINGS.zh;
    return function t(k) { return dict[k] != null ? dict[k] : k; };
  }

  // ── API helpers ───────────────────────────────────────────────────────────
  function fetchJSON(path, init) { return SDK.fetchJSON(path, init); }
  function sendJSON(method, path, body) {
    return SDK.fetchJSON(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }
  function del(path) { return SDK.fetchJSON(path, { method: "DELETE" }); }
  function errMsg(err) { return err ? (err.message || String(err)) : ""; }

  // ── date helpers (local time) ───────────────────────────────────────────
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function addMonths(d, n) { const x = new Date(d); x.setMonth(x.getMonth() + n); return x; }
  function startOfMonth(d) { const x = startOfDay(d); x.setDate(1); return x; }
  function endOfMonth(d) { return addDays(startOfMonth(addMonths(d, 1)), -1); }
  function startOfWeek(d) { const x = startOfDay(d); return addDays(x, -x.getDay()); }
  function dayKey(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }

  function eventDate(ev) {
    // For all-day "2026-06-05" Date() parses as UTC midnight; for grouping use
    // the raw date parts to avoid an off-by-one across timezones.
    if (ev.all_day && /^\d{4}-\d{2}-\d{2}$/.test(ev.start || "")) {
      const p = ev.start.split("-");
      return new Date(+p[0], +p[1] - 1, +p[2]);
    }
    const d = new Date(ev.start);
    return isNaN(d.getTime()) ? null : d;
  }
  function eventDayKey(ev) { const d = eventDate(ev); return d ? dayKey(d) : "?"; }
  function fmtTime(ev) {
    if (ev.all_day) return "整天";
    const d = new Date(ev.start);
    if (isNaN(d.getTime())) return ev.start || "";
    return pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function fmtDayHeading(d) {
    return (d.getMonth() + 1) + "/" + d.getDate() + " (" + WEEKDAYS[d.getDay()] + ")";
  }

  // datetime-local <-> ISO
  function toInputValue(iso, allDay) {
    if (!iso) return "";
    if (allDay) return /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
      + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function inputToISO(val, allDay) {
    if (!val) return "";
    if (allDay) return val.slice(0, 10);          // date-only
    const d = new Date(val);                       // parsed as local
    return isNaN(d.getTime()) ? val : d.toISOString();
  }

  // ── window for the current view ───────────────────────────────────────────
  function windowFor(view, anchor) {
    if (view === "week") {
      const s = startOfWeek(anchor);
      return [s, addDays(s, 7)];
    }
    if (view === "month") {
      const gridStart = startOfWeek(startOfMonth(anchor));
      const gridEnd = addDays(startOfWeek(endOfMonth(anchor)), 7);
      return [gridStart, gridEnd];
    }
    // list
    return [startOfMonth(anchor), addDays(endOfMonth(anchor), 1)];
  }

  // ── event editor form ─────────────────────────────────────────────────────
  function EventForm(props) {
    const t = useT();
    const ev = props.event || {};
    const isNew = !ev.id;
    const [title, setTitle] = useState(ev.title && ev.title !== "(no title)" ? ev.title : "");
    const [allDay, setAllDay] = useState(!!ev.all_day);
    const [start, setStart] = useState(toInputValue(ev.start, ev.all_day) || props.defaultStart || "");
    const [end, setEnd] = useState(toInputValue(ev.end, ev.all_day));
    const [location, setLocation] = useState(ev.location || "");
    const [description, setDescription] = useState(ev.description || "");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    function field(label, node) {
      return h("label", { className: "flex flex-col gap-1 text-sm" },
        h("span", { className: "text-xs text-muted-foreground" }, label), node);
    }
    const inputCls = "border border-border bg-transparent px-2 py-1 text-sm";

    function save() {
      const body = {
        title: title.trim() || "(no title)",
        start: inputToISO(start, allDay),
        end: inputToISO(end, allDay) || undefined,
        all_day: allDay,
        location: location.trim(),
        description: description.trim(),
      };
      setBusy(true); setError(null);
      const p = isNew
        ? sendJSON("POST", API_BASE + "/events", body)
        : sendJSON("PATCH", API_BASE + "/events/" + encodeURIComponent(ev.id), body);
      p.then(function () { if (props.onSaved) props.onSaved(); })
        .catch(function (e) { setError(t("errSave") + errMsg(e)); })
        .finally(function () { setBusy(false); });
    }

    return h(Card, { className: "mb-3", style: { borderLeft: "4px solid " + ACCENT } },
      h(CardContent, { className: "pt-4 flex flex-col gap-2" },
        field(t("fTitle"), h("input", {
          className: inputCls, value: title, autoFocus: true,
          onChange: function (e) { setTitle(e.target.value); },
        })),
        h("label", { className: "flex items-center gap-2 text-sm" },
          h("input", {
            type: "checkbox", checked: allDay,
            onChange: function (e) { setAllDay(e.target.checked); },
          }), t("fAllDay")),
        h("div", { className: "flex gap-2 flex-wrap" },
          field(t("fStart"), h("input", {
            type: allDay ? "date" : "datetime-local", className: inputCls, value: start,
            onChange: function (e) { setStart(e.target.value); },
          })),
          field(t("fEnd"), h("input", {
            type: allDay ? "date" : "datetime-local", className: inputCls, value: end,
            onChange: function (e) { setEnd(e.target.value); },
          })),
        ),
        field(t("fLocation"), h("input", {
          className: inputCls, value: location,
          onChange: function (e) { setLocation(e.target.value); },
        })),
        field(t("fDescription"), h("textarea", {
          className: inputCls, rows: 2, value: description,
          onChange: function (e) { setDescription(e.target.value); },
        })),
        error && h("p", { className: "text-sm", style: { color: "rgb(239 68 68)" } }, error),
        h("div", { className: "flex gap-2 mt-1" },
          h(Button, { onClick: save, disabled: busy || !start },
            busy ? t("saving") : t("save")),
          h(Button, { onClick: props.onCancel, disabled: busy }, t("cancel")),
        ),
      ),
    );
  }

  // ── one event row (chip in lists) ───────────────────────────────────────
  function EventRow(props) {
    const t = useT();
    const ev = props.event;
    const native = (ev.source || "native") === "native";
    const color = SOURCE_COLOR[ev.source] || ACCENT;
    return h("div", {
      className: "border border-border p-2 text-sm flex items-start gap-2",
      style: { borderLeft: "3px solid " + color },
    },
      h("div", { className: "flex flex-col gap-1 min-w-0 flex-1" },
        h("div", { className: "flex items-center gap-2 flex-wrap" },
          h("span", { className: "text-xs text-muted-foreground" }, fmtTime(ev)),
          h("span", { className: "font-medium break-all" }, ev.title || "(no title)"),
        ),
        ev.location && h("span", { className: "text-xs text-muted-foreground break-all" }, "📍 " + ev.location),
        h("div", { className: "flex items-center gap-1 flex-wrap" },
          h(Badge, { variant: "secondary" }, t("sourceLabel") + ":" + (ev.source || "native")),
        ),
      ),
      native
        ? h("div", { className: "flex gap-1 flex-none" },
          h(Button, { className: "text-xs px-2 py-1", onClick: function () { props.onEdit(ev); } }, t("edit")),
          h(Button, {
            className: "text-xs px-2 py-1", disabled: props.deleting,
            onClick: function () { props.onDelete(ev); },
          }, props.deleting ? t("deleting") : t("del")),
        )
        : h(Badge, { variant: "outline", title: t("readonlyHint") }, "🔒"),
    );
  }

  // ── list / week view (events grouped by day) ──────────────────────────────
  function DayGroups(props) {
    const t = useT();
    const days = props.days; // [{date, events}]
    if (days.every(function (d) { return d.events.length === 0; }) && !props.fixed) {
      return h("p", { className: "text-sm text-muted-foreground" }, t("noEvents"));
    }
    return h("div", { className: "flex flex-col gap-3" },
      days.map(function (g) {
        if (!props.fixed && g.events.length === 0) return null;
        return h("div", { key: dayKey(g.date), className: "flex flex-col gap-1" },
          h("div", { className: "text-sm font-medium" }, fmtDayHeading(g.date)),
          g.events.length === 0
            ? h("p", { className: "text-xs text-muted-foreground" }, "—")
            : g.events.map(function (ev) {
              return h(EventRow, {
                key: ev.id, event: ev,
                deleting: props.deletingId === ev.id,
                onEdit: props.onEdit, onDelete: props.onDelete,
              });
            }),
        );
      }),
    );
  }

  // ── month grid ────────────────────────────────────────────────────────────
  function MonthGrid(props) {
    const anchor = props.anchor;
    const byDay = props.byDay;
    const gridStart = startOfWeek(startOfMonth(anchor));
    const cells = [];
    for (let i = 0; i < 42; i++) cells.push(addDays(gridStart, i));
    const month = anchor.getMonth();
    const todayKey = dayKey(new Date());
    return h("div", null,
      h("div", { className: "grid", style: { gridTemplateColumns: "repeat(7,1fr)", gap: 2 } },
        WEEKDAYS.map(function (w) {
          return h("div", { key: "wd" + w, className: "text-xs text-center text-muted-foreground py-1" }, w);
        }),
        cells.map(function (d) {
          const key = dayKey(d);
          const evs = byDay[key] || [];
          const dim = d.getMonth() !== month;
          return h("div", {
            key: key,
            className: "border border-border p-1 cursor-pointer",
            style: {
              minHeight: 76, opacity: dim ? 0.45 : 1,
              outline: key === todayKey ? "2px solid " + ACCENT : "none",
            },
            onClick: function () { props.onPickDay(d); },
          },
            h("div", { className: "text-xs text-right text-muted-foreground" }, d.getDate()),
            h("div", { className: "flex flex-col gap-0.5 mt-0.5" },
              evs.slice(0, 4).map(function (ev) {
                return h("div", {
                  key: ev.id,
                  className: "text-xs px-1 truncate",
                  title: ev.title,
                  style: {
                    backgroundColor: (SOURCE_COLOR[ev.source] || ACCENT) + "22",
                    borderLeft: "2px solid " + (SOURCE_COLOR[ev.source] || ACCENT),
                  },
                  onClick: function (e) { e.stopPropagation(); props.onPickEvent(ev); },
                }, (ev.all_day ? "" : fmtTime(ev) + " ") + (ev.title || ""));
              }),
              evs.length > 4 && h("div", { className: "text-xs text-muted-foreground px-1" }, "+" + (evs.length - 4)),
            ),
          );
        }),
      ),
    );
  }

  // ── ICS subscriptions panel ───────────────────────────────────────────────
  function SubscriptionsPanel() {
    const t = useT();
    const [subs, setSubs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [url, setUrl] = useState("");
    const [label, setLabel] = useState("");
    const [busy, setBusy] = useState(false);
    const [refreshingId, setRefreshingId] = useState(null);
    const [notice, setNotice] = useState(null);

    const refresh = useCallback(function () {
      setLoading(true); setError(null);
      return fetchJSON(API_BASE + "/subscriptions")
        .then(function (d) { setSubs(Array.isArray(d.subscriptions) ? d.subscriptions : []); })
        .catch(function (e) { setError(t("errSub") + errMsg(e)); })
        .finally(function () { setLoading(false); });
    }, []);
    useEffect(function () { refresh(); }, [refresh]);

    function add() {
      if (!url.trim()) return;
      setBusy(true); setError(null);
      sendJSON("POST", API_BASE + "/subscriptions", { url: url.trim(), label: label.trim() })
        .then(function () { setUrl(""); setLabel(""); return refresh(); })
        .catch(function (e) { setError(t("errSub") + errMsg(e)); })
        .finally(function () { setBusy(false); });
    }
    function remove(id) {
      del(API_BASE + "/subscriptions/" + encodeURIComponent(id))
        .then(refresh)
        .catch(function (e) { setError(t("errSub") + errMsg(e)); });
    }
    function doRefresh(id) {
      setRefreshingId(id); setNotice(null);
      sendJSON("POST", API_BASE + "/subscriptions/" + encodeURIComponent(id) + "/refresh", {})
        .then(function (r) { setNotice(r && r.message ? r.message : ""); })
        .catch(function (e) { setError(t("errSub") + errMsg(e)); })
        .finally(function () { setRefreshingId(null); });
    }

    const inputCls = "border border-border bg-transparent px-2 py-1 text-sm";
    return h(Card, { style: { borderLeft: "4px solid " + ACCENT_SUB } },
      h(CardHeader, null,
        h(CardTitle, { className: "text-base" }, t("subsHeader") + " (" + subs.length + ")"),
        h("p", { className: "text-xs text-muted-foreground", style: { marginTop: 4 } }, t("subsSubtitle")),
      ),
      h(CardContent, { className: "flex flex-col gap-2" },
        h("div", { className: "flex gap-2 flex-wrap items-end" },
          h("input", {
            className: inputCls, style: { flex: "2 1 240px" }, placeholder: t("subUrl"),
            value: url, onChange: function (e) { setUrl(e.target.value); },
          }),
          h("input", {
            className: inputCls, style: { flex: "1 1 120px" }, placeholder: t("subLabel"),
            value: label, onChange: function (e) { setLabel(e.target.value); },
          }),
          h(Button, { onClick: add, disabled: busy || !url.trim() }, t("addSub")),
        ),
        error && h("p", { className: "text-sm", style: { color: "rgb(239 68 68)" } }, error),
        notice && h("p", { className: "text-sm text-muted-foreground" }, notice),
        loading && h("p", { className: "text-sm text-muted-foreground" }, t("loading")),
        !loading && subs.length === 0 && h("p", { className: "text-sm text-muted-foreground" }, t("noSubs")),
        subs.map(function (s) {
          return h("div", {
            key: s.id,
            className: "border border-border p-2 text-sm flex items-center gap-2",
            style: { borderLeft: "3px solid " + ACCENT_SUB },
          },
            h("div", { className: "flex flex-col min-w-0 flex-1" },
              h("span", { className: "font-medium break-all" }, s.label || s.url),
              h("span", { className: "text-xs text-muted-foreground break-all" }, s.url),
            ),
            h(Button, {
              className: "text-xs px-2 py-1 flex-none", disabled: refreshingId === s.id,
              onClick: function () { doRefresh(s.id); },
            }, refreshingId === s.id ? t("refreshing") : t("refresh")),
            h(Button, { className: "text-xs px-2 py-1 flex-none", onClick: function () { remove(s.id); } }, t("del")),
          );
        }),
      ),
    );
  }

  // ── main page ─────────────────────────────────────────────────────────────
  function CalendarPage() {
    const t = useT();
    const [view, setView] = useState("list");
    const [anchor, setAnchor] = useState(startOfDay(new Date()));
    const [events, setEvents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [editing, setEditing] = useState(null);   // event obj | {} (new) | null
    const [deletingId, setDeletingId] = useState(null);

    const win = useMemo(function () { return windowFor(view, anchor); }, [view, anchor]);

    const reload = useCallback(function () {
      setLoading(true); setError(null);
      const qs = "?start=" + encodeURIComponent(win[0].toISOString())
        + "&end=" + encodeURIComponent(win[1].toISOString());
      return fetchJSON(API_BASE + "/events" + qs)
        .then(function (d) { setEvents(Array.isArray(d.events) ? d.events : []); })
        .catch(function (e) { setError(t("errLoad") + errMsg(e)); })
        .finally(function () { setLoading(false); });
    }, [win]);
    useEffect(function () { reload(); }, [reload]);

    const byDay = useMemo(function () {
      const m = {};
      events.forEach(function (ev) {
        const k = eventDayKey(ev);
        (m[k] = m[k] || []).push(ev);
      });
      return m;
    }, [events]);

    function nav(dir) {
      if (dir === 0) { setAnchor(startOfDay(new Date())); return; }
      if (view === "week") setAnchor(addDays(anchor, dir * 7));
      else setAnchor(addMonths(anchor, dir));
    }

    function onSaved() { setEditing(null); reload(); }
    function onDelete(ev) {
      setDeletingId(ev.id); setError(null);
      del(API_BASE + "/events/" + encodeURIComponent(ev.id))
        .then(reload)
        .catch(function (e) { setError(t("errDelete") + errMsg(e)); })
        .finally(function () { setDeletingId(null); });
    }
    function onPickDay(d) {
      setEditing({ _defaultStart: toInputValue(d.toISOString(), false) });
    }
    function onPickEvent(ev) {
      if ((ev.source || "native") === "native") setEditing(ev);
    }

    const heading = view === "week"
      ? (startOfWeek(anchor).getMonth() + 1) + "/" + startOfWeek(anchor).getDate() + " 起這週"
      : anchor.getFullYear() + " 年 " + (anchor.getMonth() + 1) + " 月";

    // build day groups for list/week
    let dayGroups = null, fixed = false;
    if (view === "list" || view === "week") {
      const span = view === "week" ? 7 : Math.round((win[1] - win[0]) / 86400000);
      const startD = view === "week" ? startOfWeek(anchor) : startOfMonth(anchor);
      fixed = view === "week";
      dayGroups = [];
      for (let i = 0; i < span; i++) {
        const d = addDays(startD, i);
        dayGroups.push({ date: d, events: byDay[dayKey(d)] || [] });
      }
    }

    function viewBtn(key, labelKey) {
      return h(Button, {
        onClick: function () { setView(key); },
        variant: view === key ? "default" : "outline",
        className: "text-xs px-2 py-1",
      }, t(labelKey));
    }

    return h("div", { className: "flex flex-col gap-3", style: { padding: "1rem" } },
      // header
      h("div", { className: "flex items-center gap-3 flex-wrap" },
        h("h2", { className: "text-base font-medium" }, t("title")),
        h(Badge, { variant: "outline" }, "v0.1.0"),
        h("div", { className: "flex gap-1 ml-auto" }, viewBtn("list", "viewList"), viewBtn("month", "viewMonth"), viewBtn("week", "viewWeek")),
      ),
      // toolbar
      h(Card, { style: { borderLeft: "4px solid " + ACCENT } },
        h(CardHeader, null,
          h("div", { className: "flex items-center gap-2 flex-wrap" },
            h(Button, { className: "text-xs px-2 py-1", onClick: function () { nav(-1); } }, t("prev")),
            h(Button, { className: "text-xs px-2 py-1", onClick: function () { nav(0); } }, t("today")),
            h(Button, { className: "text-xs px-2 py-1", onClick: function () { nav(1); } }, t("next")),
            h(CardTitle, { className: "text-sm" }, heading),
            h(Button, { className: "ml-auto", onClick: function () { setEditing({}); } }, "+ " + t("newEvent")),
          ),
        ),
        h(CardContent, null,
          editing && h(EventForm, {
            event: editing._defaultStart ? null : editing,
            defaultStart: editing._defaultStart,
            onSaved: onSaved,
            onCancel: function () { setEditing(null); },
          }),
          error && h("p", { className: "text-sm", style: { color: "rgb(239 68 68)" } }, error),
          loading && h("p", { className: "text-sm text-muted-foreground" }, t("loading")),
          !loading && view === "month" && h(MonthGrid, {
            anchor: anchor, byDay: byDay, onPickDay: onPickDay, onPickEvent: onPickEvent,
          }),
          !loading && (view === "list" || view === "week") && h(DayGroups, {
            days: dayGroups, fixed: fixed, deletingId: deletingId,
            onEdit: function (ev) { setEditing(ev); }, onDelete: onDelete,
          }),
        ),
      ),
      // subscriptions
      h(SubscriptionsPanel, null),
    );
  }

  window.__HERMES_PLUGINS__.register(PLUGIN_NAME, CalendarPage);
})();
