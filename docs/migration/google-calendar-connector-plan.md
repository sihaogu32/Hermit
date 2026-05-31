# 行事曆系統實作計劃（P1 下一段）

> 狀態（2026-05-31 更新）：**步驟 1–3 已落地**（commit `3d0298f`：`calendar_store` / `calendar_read` / `consent_event` + `plugins/calendar` dashboard，Google read tool 降級為 source adapter，全帶測試）；**步驟 4 起未動工**（ICS 抓取／解析 `calendar_ics.py` 與 Dockerfile 的 `icalendar` 層、步驟 6 起的真網址端到端與 Google OAuth／cron）。下方〈落地步驟順序〉逐項對照。
> **改版（2026-05-31）**：方向從原本「Google Calendar connector（GCP/OAuth-first）」轉為
> **「hermit 原生行事曆 + dashboard，ICS 私人網址唯讀訂閱為主推匯入，既有 Google OAuth
> connector 降級保留作進階選項」**。改版理由見下節〈為什麼改方向〉。
> 既有資產：consent-center 骨架（commit `497fc95`）、Google OAuth 唯讀 read tool（commit
> `a321d2f`，本版降級保留、改造成 source adapter，不刪）。

## 為什麼改方向（本末倒置）

原計畫把 MVP 賣點「它真的比通用聊天更懂我」整個押在「使用者撐過 OAuth 設定」之後，但那道牆會**先把人擋掉**：

- **Google 的硬限制**：要用程式讀**私人**行事曆，呼叫端必須有一組 OAuth 2.0 Client ID，而它**只能在某個 GCP project 內、且啟用 Calendar API 才產得出來**。
- **hermit 無中央託管 app**：消費級產品會內建自家註冊好的 OAuth client，使用者只看到「用 Google 登入」；hermit 自架、沒有託管後端，所以**使用者被迫扮演 app 開發者**，自己去 GCP 建 project + client。
- **結果本末倒置**：一個主打「讓生活更輕鬆」的個人 agent，onboarding 第一步卻是「去 Google Cloud Console 開 project」——連工程背景的使用者都排斥，一般人更不可能跨過。

**結論**：把「碰 GCP」從必經之路移除。原生 + ICS 為主推（免授權／低摩擦），OAuth 留作以後想要雙向／完整同步時的 power-user 進階選項。

## 三源合併架構（原生為核心）

```
                      ┌─ ① 原生事件 (hermit 擁有)              ← 核心
  read_calendar_events│    • 使用者在 dashboard 手動增刪改
   = 讀「合併視圖」 ──┤    • agent 走 propose_event → consent 確認後落地
   (不再直連 Google)  │    存：HERMES_HOME/calendar/events.json  ← hermit 唯一會「寫」的檔
                      │
                      ├─ ② ICS 訂閱 (唯讀鏡像)                 ← 主推的低摩擦匯入
                      │    • 貼一條 Google 設定裡的私人 iCal 網址 → 抓取/解析/快取
                      │    存：HERMES_HOME/calendar/subscriptions.json + cache/
                      │
                      └─ ③ Google OAuth (唯讀, 已建好 a321d2f) ← 降級保留, 進階
                           • 既有 google_calendar.py 改造成一個 source adapter
                           • 不擋 onboarding；token 在時才放行 (check_fn)
            ↓
   dashboard (新 plugins/calendar/) 月/週/列表顯示合併結果，事件標 source；v1 含手動增刪改
```

**清楚的責任線（守紅線#5）**：hermit 只「寫」原生那一檔（`events.json`）；ICS／Google 都是**唯讀鏡像快取**，可重抓可丟，永遠不混淆「我擁有的事件」vs「外部鏡像」。agent 想新增事件一律走 `propose_event → consent`（複用既有 propose→confirm，不繞過）；使用者在 dashboard 手動加／改，則「使用者本人就是那個人工確認」。

## 已拍板的設計決策（2026-05-31）

1. **`read_calendar_events` 改角色**：從「直連 Google 讀」改成「讀**合併視圖**（native + ICS + 選配 google）」。Google 直讀降為其中一個 source。會動到 `a321d2f` 已 commit 的那顆工具：把 read tool 的註冊移到合併讀取層，**保留**其 credential 載入／自動 refresh 段，移進 google source adapter。
2. **ICS 解析補依賴 `icalendar`**（理由與安裝點見下節〈依賴決策〉）。
3. **dashboard v1 含手動增刪改**（否則原生行事曆 day-1 是空的，dashboard 沒東西可看）。

承接舊版仍成立的決策：
- **讀與提議分離**：read tool 純讀（回合併事件，不自動 propose）；「哪些值得記憶／加進行事曆」的語意判斷交給 agent，再由 agent 呼叫 `propose_event` / `propose_memory`。
- **對外／回寫動作首版不做**：把事件寫回 Google（建／刪 Google 端事件）屬高風險對外動作（紅線#5），**第一版不接**。原生事件的增刪改是寫**本地** `events.json`，不對外。

## 依賴決策：為什麼需要 `icalendar`（決策#2 的紀錄）

> 本節即決策#2 要求的「這個依賴因為什麼原因而需要」的書面紀錄。

- **ICS = iCalendar（RFC 5545），看似純文字、實則複雜**：重複事件（`RRULE` / `RDATE` / `EXDATE`）、時區定義（`VTIMEZONE`）、整日 vs 定時事件、行折疊（line folding，75 字元換行續接）、跳脫字元。
- **這個 source 的核心職責是「把重複事件正確展開成查詢視窗內的具體 occurrences」並處理時區**。自寫 stdlib parser 在 recurrence／時區上**極易出錯**（業界知名陷阱）。對行事曆而言，「漏掉的事件」或「時間錯位一小時」是**正確性紅線**，不是外觀瑕疵——使用者會因此錯過真實行程，直接打臉「它更懂我」的賣點。
- **故採標準、久經驗證的 `icalendar`（解析）＋既有 `python-dateutil`（`RRULE` 展開）**，不自幹。`dateutil` runtime 已有；只需補 `icalendar`。
- **安裝點（守紅線#3 不動 core）**：**不**加進 hermes-agent 的 `pyproject.toml`（那是上游 core 的依賴清單）。改在 **repo 自己的 `docker/Dockerfile`** 於 base 安裝後疊一層，裝進 hermes venv：
  ```dockerfile
  # 在 setup-hermes.sh（line 43-44）之後、COPY overlay 之前疊一層：
  RUN cd "${HERMES_HOME}/hermes-agent" \
   && venv/bin/uv pip install --no-cache-dir icalendar
  ```
  依賴歸我們的 connector，不污染上游依賴清單，重建可重現。

> **現況**：`icalendar` **尚未**加進 `docker/Dockerfile` 與 `ci/requirements-test.txt`（與 ICS slice 一同 deferred）。步驟 4 開工時要把「Dockerfile 疊層 + `ci/requirements-test.txt` pin + 版本鎖對齊」三處一起補（同 CLAUDE.md「升級 hermes 版本鎖」一節的三處同步紀律）。

## 紅線對齊

- **#3 不動 core**：新 tool 落 `tools/`（鏡像 `patches/hermes-agent/files/`）；額外依賴走 repo 自己的 `docker/Dockerfile` 層，不改上游 `pyproject.toml`；既有 read tool 的改造在我們的檔內完成，不碰 `agent|gateway|cron` 等核心 module。
- **#5 不靜默自動動作**：hermit 只寫原生 `events.json`；ICS／Google 為唯讀鏡像快取；agent 新增事件走 `propose_event → consent`；使用者 dashboard 手動編輯＝本人即時確認。對外回寫（建／刪 Google 事件）首版不做。
- **#1 情境 first-class**：行事曆是 productivity 情境的一個 source；命名走 `calendar` toolset / `plugins/calendar`，不 hardcode 進別處。

## 儲存形狀（沿用 consent-center 的檔案式 JSON）

對齊既有 `consent_proposals/*.json`、`consent_history/*.json` 的檔案式模式，不引入 DB：

| 路徑 | 用途 | 誰會寫 |
|---|---|---|
| `HERMES_HOME/calendar/events.json` | 原生擁有事件（手動 + agent 經 consent 確認） | **hermit（唯一 writer）** |
| `HERMES_HOME/calendar/subscriptions.json` | ICS 訂閱清單（私人 iCal URL + 標籤） | 使用者（dashboard）／setup |
| `HERMES_HOME/calendar/cache/<source>.json` | 外部來源（ICS／Google）唯讀鏡像快取 | 同步流程（可重抓、可丟） |

事件 schema（合併視圖統一形狀）：
`{ id, title, start, end, all_day, location, description, source: native|ics|google, source_ref, created_at, updated_at, status }`

## 要建／改的檔

**新增**（鏡像 `patches/hermes-agent/files/`，加進 `HA_FILES`；plugin 走 overlay 白名單）：

1. **`tools/calendar_store.py`** + `tests/tools/test_calendar_store.py`
   - 原生事件 CRUD（讀／增／改／刪 `events.json`），**唯一 writer**；原子寫入。
2. **`tools/calendar_read.py`** + `tests/tools/test_calendar_read.py`
   - 註冊 agent tool **`read_calendar_events`**（toolset `calendar`）：合併 native + ICS 快取 +（token 在時）google，依時間排序，回查詢視窗內事件。
   - `check_fn`：恆可用（原生永遠在）；ICS／google source 各自缺席時靜默略過、不報錯。
3. **`tools/calendar_ics.py`** + `tests/tools/test_calendar_ics.py`
   - ICS source：抓取私人 iCal URL → `icalendar` 解析 → `dateutil` 展開 `RRULE` 到查詢視窗 → 寫快取。抓取／解析失敗優雅降級（回空 + 記錄），不讓整個合併讀取崩掉。
4. **`tools/consent_event.py`**（或在 `consent_memory` 加事件 applier）+ 測試
   - `propose_event` agent tool：寫 `consent_proposals/*.json`（`kind=calendar_event`）→ 走既有 consent-center 確認 → apply 寫進 `calendar_store`。複用 staging／audit 形狀。
5. **`plugins/calendar/dashboard/{manifest.json, plugin_api.py, dist/index.js}`** + `plugins/calendar/tests/test_calendar_api.py`
   - 月／週／列表顯示合併視圖（事件標 source）；**v1 含手動增刪改**（呼叫 `calendar_store`，使用者操作＝人工確認）；ICS 訂閱管理（貼／刪 URL、手動 refresh）。

**修改**：

6. **`tools/google_calendar.py`**（既有 `a321d2f`）→ 降級改造成 **google source adapter**：移除自帶的 `read_calendar_events` 註冊（改由 `calendar_read` 統一註冊合併版）；**保留** credential 載入／自動 refresh 與事件抓取，導出成供 `calendar_read` 呼叫的 `fetch_events(window)` 函式。`tests/tools/test_google_calendar.py` 同步調整。
7. **`docker/Dockerfile`**：在 base 安裝後疊一層 `venv/bin/uv pip install icalendar`（見〈依賴決策〉）。
8. **`patches/hermes-agent/manifest.sh`** `HA_FILES`：加新 tools 與 tests 共 8 檔。
9. **`.hermes-overlay/manifest.sh`** `HERMES_OVERLAY_PATHS`：**顯式逐一列出** `plugins/calendar/**`（白名單已非 blanket glob，照 consent-center 那樣一檔一行加）。
10. **`.hermes-overlay/config.yaml`** `toolsets:`：啟用 `calendar`（read-only 核心低風險）。

## 落地步驟順序（步驟 1–3 完全免授權，現在就能做）

1. `calendar_store.py` + 測試（原生 CRUD，純本地全綠）。
2. `plugins/calendar/dashboard/`（顯示合併視圖 + 手動增刪改 + ICS 訂閱管理 UI）。
3. `calendar_read.py`（合併讀取 tool）+ `propose_event` 接 consent；把 `google_calendar.py` 收編成 source adapter。
4. `docker/Dockerfile` 補 `icalendar` 層；`calendar_ics.py` + 測試（餵樣本 `.ics`，含 recurring + tz）。
5. `scripts/sync_overlays.sh export` + commit（manifest／config 一併）。
6. 【**需 ICS 網址**】端到端：dashboard 貼私人 iCal URL → 看到真實行程。
7. （進階保留）Google OAuth source：沿用既有 SOP，定位成「想要比 ICS 更完整／未來雙向時才開」。
8. （後續）cron：`hermes cron create "every 1d" "讀本週行程、摘要規律、提議重要項，附 dashboard 連結" --deliver telegram`（prompt 約束只讀不寫，沿用 legal-kb-admin cron 模式）。

## 驗證

- **免授權（現在能做）**：pytest mock 全綠；`py_compile`；`read_calendar_events` 在 `calendar` toolset 註冊；dashboard 顯示合併視圖 + 手動 CRUD round-trip（加一筆 → 出現 → 改 → 刪）。
- **ICS（需樣本檔，不需真網址）**：餵含 recurring + 時區的樣本 `.ics` → 正確展開到查詢視窗、時間正確；壞 URL／抓取失敗優雅降級。
- **端到端（需真 ICS 網址）**：貼真私人 iCal URL → dashboard 顯示真實行程；agent `propose_event` → dashboard 確認 → `calendar/events.json` 出現對應條目、audit 落 `consent_history/`。

## 降級／保留的舊資產（不刪）

- **`tools/google_calendar.py` + 測試（`a321d2f`）**：改造為 google source adapter，保留 credential／refresh 邏輯；不再是 onboarding 必經，token 在時才作為一個 source 併入。
- **Google OAuth setup SOP（bundled `google-workspace` skill）**：保留為「進階：想要比 ICS 更完整、或未來要雙向同步時才做」，文件不再把它列為第一步。

## 待你確認的決策點（其餘已拍板，見上）

1. **`propose_event` 落點**：在既有 `consent_memory` 加一個事件 applier（共用一套 consent 程式）vs 新開 `consent_event.py`（職責更分）。建議**新開 `consent_event.py`**，與 memory applier 平行、各自單純。
2. **dashboard 技術形狀**：沿用 consent-center 的 `dist/index-<ver>.js` 單檔前端模式（最省事、與既有一致）vs 引入框架。建議**沿用既有單檔模式**。
3. **`calendar` toolset 預設啟用**：建議**啟用**（原生唯讀核心低風險，外部 source 各自靠 check／快取守門）。
