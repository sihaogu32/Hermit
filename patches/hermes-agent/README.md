# patches/hermes-agent/

`~/.hermes/hermes-agent` 內本地擴充的鏡像。真實 source 在 HERMES_HOME 內的 `hermes-agent`（巢狀）、**不在 repo 內**——整棵樹是 NousResearch upstream，不入 git；我們對它的擴充改鏡像到本目錄受 git 追蹤。

## 結構

```
patches/hermes-agent/
├── manifest.sh   # 白名單：HA_FILES + HA_DIFFS
├── files/        # 新增檔的鏡像（直接拷貝）
└── diffs/        # 修改檔的 git patch（.patch）
```

> **目前無自製檔**（`HA_FILES` / `HA_DIFFS` 皆空）。P1 起會在這裡新增 connector 相關工具（如資料源讀取工具），屆時把新路徑加進 `manifest.sh`。

## 取捨：files/ vs diffs/

- **新增檔** → `files/`：可直接 review、blame、grep；還原時 `sync_overlays.sh import` rsync 回 `~/.hermes/hermes-agent/`。
- **修改檔** → `diffs/`：只記錄 delta，避免把 upstream 整檔搬進來；還原時走 `git apply` 套到 `~/.hermes/hermes-agent/`。

## 維護

加 / 改擴充時：
1. 在 `~/.hermes/hermes-agent/` 內動檔（依 `wiki/project-structure.md` Extension Slots）
2. 把新路徑加進 `manifest.sh`（新增檔放 `HA_FILES`、修改檔放 `HA_DIFFS`）
3. 跑 `scripts/sync_overlays.sh export`
4. `git add patches/ && git commit`
