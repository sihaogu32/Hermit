# .hermes-overlay/

`~/.hermes` 內客製擴充點的鏡像。真實 runtime home 是 HERMES_HOME（Docker 內 `/root/.hermes`、上游預設 `~/.hermes`）、不在 repo 內；整個 `~/.hermes` 不入 git（避免 runtime 狀態 — `state.db`、`sessions/`、`logs/`、`auth.json` 等 — 污染 git），擴充點改鏡像到本目錄受 git 追蹤。

## 結構（與 `~/.hermes` 對應）

| 鏡像路徑 | 對應 `~/.hermes/` 路徑 | 用途 |
|---|---|---|
| `SOUL.md` | `~/.hermes/SOUL.md` | agent 整體人格 / 邊界（繁中 native、來源透明、不靜默自動動作） |
| `config.yaml` | `~/.hermes/config.yaml` | 模型 / tool / gateway / UI 設定（**不含 secrets**） |
| `memories/MEMORY.md` | `~/.hermes/memories/MEMORY.md` | agent 自寫的長期 memory |
| `memories/USER.md` | `~/.hermes/memories/USER.md` | user profile（agent 寫） |
| `skills/*` | `~/.hermes/skills/*` | 自製 skill（目前無，預留 glob 槽；P1+ 加入） |
| `plugins/*` | `~/.hermes/plugins/*` | 自製 dashboard plugin（目前無，預留 glob 槽；P1 connector + 同意中心起加入） |

未列入鏡像的 `~/.hermes` 子目錄一律是 runtime 狀態，**不該備份**。完整白名單見 `manifest.sh`。

## 維護

由 `scripts/sync_overlays.sh` 雙向同步（同步目標為 HERMES_HOME）— **不要手動編輯這裡的檔案**，動實況再 export：

```bash
# 改完 ~/.hermes/SOUL.md 等
scripts/sync_overlays.sh export
git add .hermes-overlay/ && git commit
```
