# Google Calendar Connector 實作計劃（P1 下一段）

> 狀態：**規劃中、未動工**（2026-05-30）。本檔是「接真 Google Calendar」的實作藍圖，供審閱後再決定動工。consent-center 骨架已於 commit `497fc95` 落地。

## Context

P1 第一刀（consent-center plugin 骨架）已完成：`propose_memory` → staging → dashboard 人工確認 → `apply_proposal` 寫受管記憶。proposal schema 已預留 `source="google_calendar"` 與 `source_ref`。

本段把 staging fixture 換成**真實 Google Calendar 讀取**：agent 能讀「今天／本週」行程，挑值得記住的，透過既有 `propose_memory` 提議，走既有 consent 流程確認。這是 hermit MVP 賣點「它真的比通用聊天更懂我 × 把答案變成行動」的第一個真資料源。

## 重用盤點（基礎設施已齊全，不必從零造）

| 已有資產 | 位置 | 用途 |
|---|---|---|
| OAuth PKCE 授權流程（scope 已含 `calendar`） | `~/.hermes/skills/productivity/google-workspace/scripts/setup.py` | 一次性授權，產 `HERMES_HOME/google_token.json` |
| credential 載入 + 自動 refresh | `.../google-workspace/scripts/google_api.py:177-196`（`get_credentials`） | `Credentials.from_authorized_user_file` + `creds.refresh(Request())` 回寫 |
| 事件讀取形狀範本 | `.../google_api.py:460-510`（`calendar_list`） | `events().list(timeMin/timeMax/singleEvents/orderBy)`；欄位 id/summary/start/end/location/description/status/htmlLink |
| Google API 全棧 | venv 已裝 `google-api-python-client==2.194.0`、`google-auth-oauthlib==1.3.1` | 無需 pip install |
| 提議 + 確認 | `tools/consent_memory.py`、`tools/consent_propose_tool.py`、`plugins/consent-center/`（已完成） | proposal → 人工確認寫入 |

## 設計（接法）

```
[一次性] 使用者跑 setup.py 授權 ──→ HERMES_HOME/google_token.json
                                          │
[執行期] agent 呼叫 read_calendar_events ─┤ tools/google_calendar.py 讀 token、讀事件（read-only）
                                          │   回傳事件清單（不自動寫任何東西）
            agent 看完事件、語意判斷 ──────┤ 挑值得記住的，呼叫 propose_memory（既有）
                                          │   → 寫 staging proposal（source=google_calendar, source_ref=事件id）
            使用者在 dashboard 勾選確認 ───┘ consent-center plugin（既有）→ apply_proposal 寫受管記憶
```

**關鍵設計選擇：讀與提議「分離」**（建議）。`read_calendar_events` 是**純讀 deterministic tool**（只回事件，不自動 propose）；「哪些事件值得記憶」的語意判斷交給 agent，再由 agent 呼叫 `propose_memory`。理由：deterministic tool 不該做語意挑選；分離後 read tool 好測試、職責單一，且提議仍統一走既有 consent 路徑（紅線#5 不破）。

## 紅線對齊

- **讀取工具可暴露為 agent tool**：行事曆「讀」是 read-only、低風險，符合讓 agent 直接用。寫入個人記憶仍只走 `propose_memory` → consent（不繞過）。
- **對外／回寫動作首版不做**：`calendar_create` / `calendar_delete`（建/刪事件）屬高風險對外動作（紅線#5），**第一版不接**；要接時走 consent 同款「人工確認入口」，不自動。
- **不動 core**（紅線#3）：新增 `tools/google_calendar.py`（鏡像 `patches/hermes-agent/files/`），不改 hermes-agent core；OAuth 沿用既有 bundled skill。
- **credential 自包含**：`tools/google_calendar.py` 自帶輕量 credential 載入（讀同一個 `google_token.json`、用 `google.oauth2.credentials`），**不** import bundled skill 腳本（skill 腳本非 module、耦合不乾淨）。credential 邏輯約 15 行，照抄 `google_api.py:177-196` 的模式。

## 要建的檔

1. **`hermes-agent/tools/google_calendar.py`**（鏡像 `patches/hermes-agent/files/tools/`，加 `HA_FILES`）
   - `_token_path()` = `get_hermes_home()/ "google_token.json"`
   - `_load_credentials()`：`Credentials.from_authorized_user_file` + expired 時 `refresh(Request())` 回寫（照抄既有模式）
   - `read_calendar_events(calendar_id="primary", days_ahead=7, max_results=50) -> dict` handler：讀事件，回 `{"status":"ok","event_count":n,"events":[{id,summary,start,end,location,description,...}]}`；token 不存在回 `{"status":"needs_auth","message":"..."}`（指引跑 setup.py）。
   - **module body top-level `registry.register(name="read_calendar_events", toolset="google-calendar", ..., check_fn=_token_exists)`**：read tool 是 agent tool（與 consent_memory 不同，這顆**要**註冊）；`check_fn` 檢查 `google_token.json` 存在，沒授權時工具不可用、不報醜錯。
   - toolset `google-calendar`：是否預設啟用列入 hermit profile `config.yaml` `toolsets:`——建議**啟用**（read-only 低風險），但只有 token 在時 check_fn 才放行。

2. **`hermes-agent/tests/tools/test_google_calendar.py`**（鏡像同上，加 `HA_FILES`）
   - mock `google.oauth2.credentials.Credentials` 與 `googleapiclient.discovery.build`，注入 fake `events().list().execute()` 回傳樣本事件。
   - 覆蓋：正常讀取與欄位解析；token 不存在回 `needs_auth`（不呼叫 API）；expired token 觸發 refresh 回寫；空行事曆；`days_ahead` 換算 timeMin/timeMax。
   - **不打真 API、不需真 token**。

3. （可選，未來再抽）`tools/_google_auth.py`：把 credential 載入抽成共用 helper，供日後 gmail/drive connector 重用。第一刀先內嵌於 `google_calendar.py`，不預先抽象。

## OAuth 一次性設定 SOP（使用者親自做，我無法代勞）

1. 到 Google Cloud Console 建（或選）一個 project，啟用 **Google Calendar API**。
2. 建 **OAuth 2.0 Client ID**（類型 Desktop app 最省事），下載 `client_secret.json`。
3. 在 runtime 跑既有 skill 的設定流程（路徑：`~/.hermes/skills/productivity/google-workspace/scripts/`）：
   ```
   python setup.py --install-deps              # venv 已裝可略
   python setup.py --client-secret /path/to/client_secret.json
   python setup.py --auth-url                  # 印授權 URL → 瀏覽器登入授權
   python setup.py --auth-code <貼回授權碼>
   python setup.py --check                     # 驗證；成功後 google_token.json 就緒
   ```
   > 這些指令需要互動（瀏覽器授權），請用 prompt 列 `! <command>` 在本 session 直接跑，輸出會回到對話。
4. 完成後 `HERMES_HOME/google_token.json` 存在，`read_calendar_events` 的 `check_fn` 即放行。

## 落地步驟順序（OAuth 就緒前可做到步驟 4）

1. 寫 `tools/google_calendar.py`（read tool + credential 載入 + register）。
2. 寫 `tests/tools/test_google_calendar.py`（mock，全綠）。
3. 更新 `patches/hermes-agent/manifest.sh` `HA_FILES`（加兩檔）；若 toolset 要預設啟用，改 `.hermes-overlay/config.yaml` `toolsets:`。
4. `scripts/sync_overlays.sh export` + commit。
5. 【**需 OAuth 就緒**】使用者跑 SOP 授權。
6. 【需 OAuth 就緒】真實端到端：CLI 對話讓 agent `read_calendar_events` → 看事件 → `propose_memory` → dashboard 確認 → 受管記憶出現。
7. （後續）cron 觸發：`hermes cron create "every 1d" "讀本週行程、摘要規律、提議重要項寫入記憶，附 dashboard 連結" --deliver telegram`（沿用 legal-kb-admin cron 模式；prompt 約束只讀不寫）。

## 驗證

- **OAuth 前（現在能做）**：pytest mock 全綠；`py_compile`；確認 register 後 `read_calendar_events` 在 `google-calendar` toolset、`check_fn` 在無 token 時回不可用。
- **OAuth 後（真實端到端）**：真讀 primary calendar 本週事件；agent 提議 → dashboard 勾選確認 → `memories/managed/CONFIRMED.md` 出現對應條目、audit 落 `consent_history/`。

## 待你確認的決策點

1. **讀與提議分離 vs 合一**：建議「分離」（read tool 純讀、agent 判斷後 propose）。若想要 read tool 讀完就自動提議全部事件，可改「合一」（但失去語意挑選）。
2. **toolset 是否預設啟用**：建議啟用 `google-calendar`（read-only，靠 check_fn 守 token）。若想更保守可預設關、用時才開。
3. **讀取範圍**：建議第一版 `primary` 行事曆、未來 7 天。要不要含過去事件 / 多行事曆，後續再加參數。
4. **對外動作**：第一版只讀，不接建/刪事件。確認此邊界。
