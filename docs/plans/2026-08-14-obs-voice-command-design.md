# obs-voice-command 設計文件

日期：2026-08-14
狀態：已驗證（與使用者逐段確認）

## 目標

直播時用語音指令控制 OBS 畫面縮放：說「來個特寫」→ zoom in 到滑鼠位置並持續追蹤滑鼠；說「退回全畫面」→ 緩動回 1x 全畫面。

## 關鍵決策

| 決策點 | 選擇 | 理由 |
| --- | --- | --- |
| 語音偵測 | 串流 ASR + 關鍵詞比對（sherpa-onnx） | 不用錄音訓練、新增指令只要打字、抗雜訊強；捨棄錄音模板比對（準確率差）與 KWS 專用模型（自訂詞準確率不足） |
| 實作形式 | 外部 Python daemon + obs-websocket | 開發快、好除錯、OBS 升版不會壞；捨棄原生 C++ plugin（成本 5-10 倍）與 OBS 內建 Python script（依賴難裝） |
| 縮放行為 | 持續追蹤滑鼠（deadzone + 緩動） | 適合邊講邊操作的直播 |
| 追蹤邏輯位置 | Python 端（不用 obs-zoom-to-mouse Lua） | 該 script 在 macOS Retina 有已知座標問題；單一 codebase 好維護 |

## 架構

```
┌─────────────────────────────────────────┐
│  obs-voice-command (Python daemon)      │
│                                         │
│  ┌──────────┐   ┌──────────────────┐    │
│  │ Mic 音訊  │──▶│ sherpa-onnx      │    │
│  │(sounddevice)│ 串流中文 ASR      │     │
│  └──────────┘   └────────┬─────────┘    │
│                          │ 即時文字      │
│                 ┌────────▼─────────┐    │
│                 │ 關鍵詞比對器       │    │
│                 └────────┬─────────┘    │
│                          │ 指令事件      │
│  ┌──────────┐   ┌────────▼─────────┐    │
│  │ 滑鼠座標   │──▶│ Zoom 控制器      │    │
│  │ (Quartz) │   │ (追蹤+緩動迴圈)   │     │
│  └──────────┘   └────────┬─────────┘    │
└──────────────────────────┼──────────────┘
                           │ obs-websocket (localhost:4455)
                    ┌──────▼──────┐
                    │     OBS     │
                    └─────────────┘
```

資料流：麥克風 → ASR partial 文字 → 關鍵詞比對 → 指令事件 → Zoom 控制器以 ~30fps 讀滑鼠、算 transform、送 `SetSceneItemTransform`。

## 語音偵測

- **模型**：`sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20`（int8 約 100MB），純 CPU 即時。首次啟動自動下載到 `~/.cache/obs-voice-command/`。
- **音訊**：`sounddevice` 開系統預設麥克風，16kHz mono。macOS 允許多 app 共用麥克風，不影響 OBS 收音。
- **比對策略**：
  1. 比對 partial results，不等句尾（延遲 0.3–0.6s）
  2. 辨識文字與關鍵詞都轉 pinyin（`pypinyin`，忽略聲調）做子字串比對，容忍同音錯字
  3. Debounce：記錄已觸發的文字位置，同句不重複觸發；另加 2 秒冷卻
  4. 狀態感知：zoomed 時忽略 zoom_in，全畫面時忽略 zoom_out
- **指令表**：TOML 設定，`phrases`（關鍵詞列表）+ `action`。

## Zoom 控制與滑鼠追蹤

**Transform 數學**（crop 不動，改 scale + position）：

```
scale = base_scale × z          # z 預設 2.0
position = canvas_center − (mx, my) × scale
position = clamp(position)      # 不露黑邊
```

**macOS 陷阱**：
- Retina：Quartz 回傳 points，OBS 是 pixels；用 `CGDisplayPixelsWide` 對照 source 寬度算比例
- 多螢幕：全域座標先減掉所在螢幕 origin；滑鼠在非擷取螢幕時追蹤凍結

**追蹤迴圈**（30fps）：讀滑鼠 → deadzone（預設可視範圍 15%，內部不動）→ 更新目標 → 指數平滑 `current += (target − current) × 0.12` → 送 transform。

**進出場**：0.5s ease-out。啟動時 `GetSceneItemTransform` 存原始 transform，zoom out / 退出 / 崩潰恢復都復原到它。

**目標 source**：設定檔指定 scene + source；未指定則自動找 program scene 第一個 display capture。

## 設定檔（config.toml，全部可選）

```toml
[obs]
host = "localhost"
port = 4455
password = ""
scene = ""          # 空 = 自動偵測
source = ""

[zoom]
level = 2.0
deadzone = 0.15
smoothing = 0.12

[audio]
device = ""         # 空 = 系統預設

[[commands]]
phrases = ["來個特寫", "放大一點"]
action = "zoom_in"

[[commands]]
phrases = ["退回全畫面", "拉遠"]
action = "zoom_out"
```

## 錯誤處理（原則：永遠不能把畫面搞壞）

- OBS 斷線 → 每 3 秒重連；期間指令丟棄並記 log
- 重連後檢查 transform，發現殘留的 zoom 狀態 → 復原原始 transform
- 退出（含 Ctrl-C）→ cleanup handler 復原 transform
- 找不到 display capture → 啟動即報錯退出
- 麥克風權限 → 印出開權限指引

## 可觀測性

終端機即時印 ASR partial（淡色）+ 觸發事件（高亮）。`--dry-run`：只印不動 OBS。

## 測試策略

- **Unit**：關鍵詞比對器（同音、debounce、狀態機）、transform 數學（座標換算、clamp、Retina）— 純函數
- **Integration**：預錄 wav 餵 ASR pipeline，驗證觸發序列
- **手動 E2E**：`--dry-run` 對 OBS 實測

## 專案結構

`uv` + venv。模組：`config.py` / `matcher.py` / `zoom.py`（純數學）/ `mouse.py` / `asr.py` / `obs_client.py` / `main.py`。
