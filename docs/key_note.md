# Key Notes

開發 hermit 時踩到、值得記住的關鍵脈絡。每則附日期與「為什麼」。

---

## hermes 的 platform 與 toolset 曝露機制（2026-05-31 試錯紀錄）

### TL;DR

一個 toolset（含 registry 動態註冊的，如 `calendar`）要真的曝露給 agent，必須加進
`config.yaml` 的 **`platform_toolsets.<platform>`**。**頂層 `toolsets:` 清單對 platform
session 完全被忽略**。dashboard / 本機聊天走的是 **`cli`** 平台。

### platform 是什麼

在 hermes 裡，**platform 指「這場對話從哪個管道／前端進來」**——同一顆 agent 大腦，多扇前門。
（注意：**不是**作業系統 Windows/Linux/Mac，那個在程式裡是 `sys.platform`，是另一回事。）

| platform（config key） | 程式內 enum | 管道 |
|---|---|---|
| `cli` | `Platform.LOCAL` | 本機終端機 CLI **以及 dashboard 網頁聊天（port 9119）** |
| `api_server` | `Platform.API_SERVER` | 對外 gateway / HTTP API |
| `telegram` / `discord` / `slack` / `whatsapp` / `matrix`… | 各自 enum | 各家聊天機器人接口 |

平台字串的決定：`gateway/run.py` 的 `_platform_config_key()` →「`Platform.LOCAL` 對應 `cli`，
其餘用 `platform.value`」。dashboard 聊天經實測（agent.log 顯示 `platform=cli`）走 `cli`。

### 為什麼要分 platform：每個管道的信任度不同

不同管道的信任程度與適用能力天差地別，所以工具能力要分管道控管：

- 本機 dashboard / CLI（`cli`）＝你本人在操作，可給近乎全套工具（`terminal`、`computer_use`、檔案、行事曆…）。
- 對外的 Telegram bot（`telegram`）＝任何人都能傳訊息進來，絕不該讓它跑 shell 或操控桌面，只開很窄的一組。

這就是 **`platform_toolsets` ＝「每個管道各自的工具白名單」**。

### 解析邏輯（單一真相）

`hermes_cli/tools_config.py` 的 `_get_platform_tools(config, platform)`：

1. 讀 `platform_toolsets[platform]`；
2. 若該 platform 沒列出 → 退回該平台的**預設工具集**（`cli` 預設 = `hermes-cli`）；
3. **從不參考頂層 `toolsets:`**。

也就是說頂層 `toolsets:` 比較像「全域預設／遺留欄位」，真正決定「這個管道曝露什麼」的是
`platform_toolsets.<platform>`，且它是**白名單（直接替代），不與頂層交集、也不附加**。

### 這次的試錯（症狀 → 根因 → 修正）

- **症狀**：dashboard 新增的行事曆事件正常存進 `~/.hermes/calendar/events.json`（dashboard 寫入路徑沒問題），
  但在 dashboard 問 agent「我現在有什麼行事曆」，它**只會去搜 Google**，撞 `No token at google_token.json`。
- **調查**：agent.log 顯示該 session `platform=cli`，且它**根本沒呼叫 `read_calendar_events`**——
  退去跑 google-workspace skill。
- **根因**：calendar connector 落地時只把頂層 `toolsets:` 改成 `calendar`，但 dashboard chat 走 `cli` 平台，
  而 `platform_toolsets.cli` 只有 `hermes-cli`、沒有 `calendar` → 合併版 `read_calendar_events`
  根本沒曝露給 agent。
- **修正**：把 `calendar` 加進 `platform_toolsets.cli`。實測該平台即曝露 `read_calendar_events` + `propose_event`。

### 教訓 / 未來加 toolset 的 checklist

1. 新增 registry toolset 後，要在 **`platform_toolsets.<目標平台>`** 列出它，光改頂層 `toolsets:` 沒用。
   - dashboard / 本機 → `cli`；對外 API/gateway → `api_server`；Telegram → `telegram`…**一扇門一份白名單**。
2. 改完要**重啟 hermes 程序**：tool registry 由 `discover_builtin_tools()` 在 process 啟動時載入一次，
   新註冊的 tool 要重啟才會進 registry（config 雖多為 per-session 重讀，但 registry 不是）。
3. 驗證指令（確認某 tool 是否會被某平台曝露）：
   ```bash
   cd ~/.hermes/hermes-agent && venv/bin/python -c "
   from tools.registry import discover_builtin_tools; discover_builtin_tools()
   from hermes_cli.tools_config import _get_platform_tools
   from hermes_cli.web_server import load_config
   from toolsets import resolve_toolset
   ts=_get_platform_tools(load_config(),'cli'); tools=set()
   for t in ts:
       try: tools|=set(resolve_toolset(t))
       except Exception: pass
   print('read_calendar_events 曝露?', 'read_calendar_events' in tools)
   "
   ```

相關 commit：`calendar` 免授權核心（feat(calendar) …）含 `platform_toolsets.cli` 修正。
