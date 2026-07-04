# Auto Highlight Editor

這是一個「自動剪精華影片」的小工具。

你給它一支很長的影片，它會幫你找出比較可能有趣、重要、好笑、適合剪出來的片段，最後做成一支短短的精華影片。

你可以把它想成：

```text
長影片
  -> 轉成文字和時間點
  -> 找出可能精彩的地方
  -> 幫每段打分數
  -> 排好剪輯順序
  -> 輸出 highlight.mp4
```

## 這個工具可以做什麼？

它可以幫你：

- 從影片抽出聲音
- 用 `faster-whisper` 把聲音變成逐字稿
- 找出可能是精華的片段
- 用規則幫片段打分數
- 產生剪輯計畫 `edit_plan.json`
- 用 `ffmpeg` 輸出最後的精華影片

最後完成的影片會在：

```text
work/video1/output/highlight.mp4
```

## 為什麼不直接叫 AI 看整支影片？

因為整支影片通常很大，直接丟給 AI 會很慢，也可能很貴。

這個專案的做法比較省：

1. 先用便宜的工具把影片整理成文字、時間點、縮圖。
2. 再用規則找出「可能精彩」的小片段。
3. 真的需要 AI 時，只讓 AI 看小片段，不看整支影片。

這樣比較快、比較省，也比較容易知道哪一步出錯。

## 需要安裝什麼？

一定要有：

- Python 3.10 以上
- `uv`：用來執行 Python 專案
- `ffmpeg` 和 `ffprobe`：用來處理影片和聲音
- `faster-whisper`：用來把聲音轉成文字

可選，但很有用：

- 不需要本機 LLM 或額外憑證；預設流程維持 deterministic / heuristic

## macOS 安裝方式

如果你有 Homebrew，可以這樣裝：

```bash
brew install ffmpeg uv
uv sync --extra transcribe
```

## Linux 安裝方式

以 Ubuntu / Debian 為例：

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra transcribe
```

## Windows 安裝方式

Windows 可以用這些方式：

- 用 `winget` 安裝 `ffmpeg`
- 從 Astral 官方安裝 `uv`

```bash
uv sync --extra transcribe
```

## 最簡單的使用方式

假設你的影片叫 `input.mp4`，想先用預設規則剪成一支精華：

```bash
uv run python auto_highlight.py run input.mp4 --out work/video1
```

這會跑完整流程：

```text
準備音訊
  -> 產生逐字稿
  -> 找候選片段
  -> 幫片段打分
  -> 做剪輯計畫
  -> 輸出影片
```

完成後看這個檔案：

```text
work/video1/output/highlight.mp4
```

## 內容優先剪輯

如果是旅遊、景點、展覽、街景、動物、戶外活動這類影片，不建議先用秒數決定內容。可以改用 `--selection-mode content-first`，讓工具先挑精彩、有趣、亮眼景點或畫面清楚的片段，再用秒數當安全護欄，避免成片失控太長。

推薦指令：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --visuals \
  --selection-mode content-first \
  --quality-mode auto \
  --review-mode auto
```

這個模式尤其依賴 `--visuals`，因為它會抽縮圖、把視覺線索整理成可判斷的資料，再把湖景、老街、展覽、動物、山景、特殊建築等視覺亮點納入選片。沒有設定 `--target-duration` 時，工具仍會用預設 retention ratio 算出一個長度護欄，但不會為了湊秒數硬塞弱片段。

`--quality-mode auto` 會看最後入選片段的亮度、銳利度和室內外比例，自動在 1080p、1440p、4K 之間選輸出規格。多數片段是低光室內或粗顆粒時會偏向 1080p；多數是清楚戶外景點時才會輸出 4K。

## 剪輯風格 preset

如果你想讓工具用不同口味挑片，可以加 `--profile`：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --profile travel \
  --visuals \
  --selection-mode content-first
```

目前內建：

- `default`：一般精華
- `travel`：旅遊、景點、展覽、地標、美食、戶外畫面
- `family`：家人、小孩、寵物、反應、互動
- `teaching`：教學、示範、重點句、結論
- `funny`：好笑、驚訝、短節奏反應

查看內建 profile：

```bash
uv run python auto_highlight.py profiles
```

也可以用自己的 JSON：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --profile-file my_profile.json
```

每次 run 會把當次設定寫到：

```text
work/video1/highlight_profile.json
```

之後 `score` 會讀這份設定，並在 `scored_segments.json` 裡留下 `profile_score`、`profile_adjusted_from` 和 `profile_name`，方便檢查 preset 影響了哪些片段。

## 加上縮圖分析

如果你想讓工具也看影片縮圖，可以加上 `--visuals`。這一步同樣不需要本機 LLM：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --target-duration 180 \
  --visuals
```

縮圖和視覺摘要會留給後續的規則流程與 Codex 審稿來判斷。

## 片段打分

預設會走 deterministic / heuristic 規則，不依賴本機 LLM。複雜審稿由主 Codex agent（`gpt-5.5`）處理；簡單側任務可以另派 `gpt-5.4-mini` 子代理處理。這不是使用者要填的參數。

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --target-duration 180
```

如果你沒有特別指定，流程就維持純規則打分。

## 分段執行

如果影片很長，建議分段跑。這樣中途失敗時，不用全部重來。

```bash
uv run python auto_highlight.py prepare input.mp4 --out work/video1
uv run python auto_highlight.py analyze-visuals work/video1
uv run python auto_highlight.py score work/video1
uv run python auto_highlight.py plan work/video1 --selection-mode content-first
uv run python auto_highlight.py review-gate work/video1
uv run python auto_highlight.py review-summary work/video1
uv run python auto_highlight.py subtitles work/video1
uv run python auto_highlight.py doctor work/video1
uv run python auto_highlight.py render work/video1 --quality-mode auto
```

每一步在做什麼：

| 步驟 | 指令 | 白話說明 |
| --- | --- | --- |
| 1 | `prepare` | 把影片聲音拿出來，產生逐字稿 |
| 2 | `analyze-visuals` | 抽縮圖，提供後續內容判斷所需的視覺摘要 |
| 3 | `score` | 幫候選片段打分數；預設走 deterministic / heuristic |
| 4 | `plan` | 決定最後要剪哪些片段；可用 `--selection-mode content-first` 先看內容亮點 |
| 5 | `review-gate` | 檢查剪輯計畫可信度，必要時交給 Codex CLI 審稿 |
| 6 | `review-summary` | 用人看得懂的方式列出信心檢查、已選片段和 near misses |
| 7 | `subtitles` | 從逐字稿和剪輯計畫產生 `subtitles.srt` 和 `subtitles.vtt` |
| 8 | `doctor` | 檢查 artifact 是否缺漏、過期或和來源影片不一致 |
| 9 | `render` | 真的輸出精華影片；可用 `--quality-mode auto` 自動選 1080p、1440p 或 4K |

## 輸出資料夾長什麼樣？

每次執行會產生一個 `work/<名字>/` 資料夾，例如：

```text
work/video1/
  source.json
  audio.wav
  transcript.json
  candidates.json
  visual_segments.json
  scored_segments.json
  project.summary.json
  edit_plan.json
  plan_confidence.json
  gpt_review_packet.json
  review_report.md
  review_report.html
  subtitles.srt
  subtitles.vtt
  clips/
  thumbnails/
  output/
    highlight.mp4
```

幾個重要檔案：

| 檔案 | 用途 | 白話說明 |
| --- | --- | --- |
| `transcript.json` | 逐字稿 | 影片裡每句話在第幾秒說 |
| `candidates.json` | 候選片段 | 可能值得剪出來的片段 |
| `scored_segments.json` | 分數 | 每段為什麼分數高或低 |
| `edit_plan.json` | 剪輯計畫 | 最後要剪哪幾段 |
| `plan_confidence.json` | 信心檢查 | 判斷目前計畫是 green、yellow 還是 red |
| `gpt_review_packet.json` | 審稿資料包 | 給 Codex CLI 接手 yellow/red 時看的摘要資料 |
| `review_report.html` | 圖文審稿頁 | 用瀏覽器查看 selected clips、near misses、縮圖和分數 |
| `subtitles.srt` / `subtitles.vtt` | 字幕 | 對齊最後 highlight 時間軸的字幕檔 |
| `output/highlight.mp4` | 成品 | 最後的精華影片 |

## 檢查工作資料夾狀態

如果你不確定目前 `work/video1` 裡的檔案是不是同一輪 pipeline 產生的，可以跑：

```bash
uv run python auto_highlight.py doctor work/video1
```

它會檢查：

- 來源影片是否還是同一個檔案
- 必要 artifact 是否存在
- `review_report.html`、字幕、成品影片是否比上游檔案舊
- `edit_plan.json` 的時間範圍是否有效、有沒有重疊

結果也會寫到：

```text
work/video1/doctor_report.json
```

## Codex CLI 審稿模式

這個專案的日常使用方式是：你打開 Codex CLI，叫它幫你剪影片。Python pipeline 本身維持 deterministic / heuristic，不需要本機 LLM，也不要求額外設定。

目前已加入第一版 Scheme C confidence gate：

```text
green: 本地剪輯計畫可信，直接 render
yellow: Codex CLI 接手審稿，只做小修改
red: Codex CLI 接手重排，從候選片段中救回可用剪輯
```

你可以單獨跑：

```bash
uv run python auto_highlight.py review-gate work/video1
```

如果想先快速看目前計畫、觸發規則、near misses 和下一步指令，可以跑：

```bash
uv run python auto_highlight.py review-summary work/video1
```

也可以在完整流程中加上：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --visuals \
  --selection-mode content-first \
  --quality-mode auto \
  --review-mode auto
```

如果結果是 green，流程會繼續 render。如果結果是 yellow 或 red，程式會先停在 render 前，留下 `plan_confidence.json` 和 `gpt_review_packet.json`，讓主 Codex agent（`gpt-5.5`）讀 `edit_plan.json`、`scored_segments.json`、`review_report.json`、縮圖與 near misses 後接手判斷。對於單純的整理、摘要、檢查之類側任務，Codex CLI 可以另派 `gpt-5.4-mini` 子代理處理。

Codex CLI 接手後，會寫一份 `codex_review_result.json`。接著用程式驗證並套用：

```bash
uv run python auto_highlight.py apply-review work/video1
uv run python auto_highlight.py render work/video1 --quality-mode auto
```

`apply-review` 會檢查 segment id、重疊、時長和來源範圍。通過後會備份原本的 `edit_plan.json` 成 `edit_plan.before_codex_review.json`，再更新新的 `edit_plan.json`。

`codex_review_result.json` 可用這些格式：

```json
{
  "version": "codex_review_result_v1",
  "decision": "approve",
  "reason": "current plan is good"
}
```

```json
{
  "version": "codex_review_result_v1",
  "decision": "revise",
  "reason": "replace a weak ending with a stronger near miss",
  "operations": [
    {"op": "replace", "remove": "seg_010", "add": "seg_012"},
    {"op": "reorder", "segment_ids": ["seg_000", "seg_012", "seg_008"]}
  ]
}
```

```json
{
  "version": "codex_review_result_v1",
  "decision": "rerank",
  "reason": "red rescue plan",
  "selected_segment_ids": ["seg_000", "seg_012", "seg_008"]
}
```

相關長期實作計畫在：

```text
gpt_review_scheme_c_plan.md
```

## 演算法怎麼想？

演算法就是「程式做決定的方法」。

這個工具會看幾種線索：

- 有沒有出現關鍵字，例如 `哈哈`、`哇`、`你看`、`景點`、`好吃`
- 這段話多不多
- 有沒有一來一往的互動
- 有沒有情緒，例如驚訝、好笑、興奮
- 有沒有地點或景物
- 縮圖裡有沒有看起來重要的畫面

簡單版公式可以想成：

```text
總分 =
  關鍵字分數
  + 說話密度
  + 互動感
  + 情緒
  + 地點價值
  + 視覺亮點
  - 品質扣分
```

分數高的片段比較有機會被放進最後的精華影片。

## HTML 圖文說明

專案裡有一份比較像教學網頁的文件：

```text
project-guide.html
```

你可以直接用瀏覽器打開它。它用更簡單的方式說明：

- 怎麼使用這個工具剪片
- 要先安裝什麼
- 演算法流程圖
- 輸出檔案是什麼

## 測試

執行測試：

```bash
uv run python -m unittest discover -s tests
```

目前測試會檢查：

- 時間格式有沒有算對
- 候選片段有沒有找對
- 片段合併有沒有正常
- 縮圖和視覺資訊有沒有接上
- 分數計算有沒有基本正常

## 不要上傳哪些東西？

請不要把這些東西放進 GitHub：

- 原始影片
- 剪好的影片
- 抽出來的音訊
- 私人影片的逐字稿
- 縮圖
- `.env` 檔
- 外部服務憑證
- 大型快取

這些通常會放在 `work/` 裡，而且 `.gitignore` 已經設定好不要上傳。

## 授權

本專案使用 MIT License。詳情請看 `LICENSE`。
