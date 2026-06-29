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
- 用規則或本機 AI 幫片段打分數
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

- `ollama`：在你自己的電腦跑 AI 模型
- `qwen3:1.7b`：用來看文字片段，幫片段打分
- `qwen2.5vl:7b`：用來看縮圖，描述畫面裡有什麼

## macOS 安裝方式

如果你有 Homebrew，可以這樣裝：

```bash
brew install ffmpeg uv ollama
uv sync --extra transcribe
ollama pull qwen3:1.7b
ollama pull qwen2.5vl:7b
```

## Linux 安裝方式

以 Ubuntu / Debian 為例：

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra transcribe
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:1.7b
ollama pull qwen2.5vl:7b
```

## Windows 安裝方式

Windows 可以用這些方式：

- 用 `winget` 安裝 `ffmpeg`
- 從 Astral 官方安裝 `uv`
- 從 Ollama 官方網站安裝 Ollama

安裝模型：

```bash
uv sync --extra transcribe
ollama pull qwen3:1.7b
ollama pull qwen2.5vl:7b
```

## 最簡單的使用方式

假設你的影片叫 `input.mp4`，想剪成大約 180 秒：

```bash
uv run python auto_highlight.py run input.mp4 --out work/video1 --target-duration 180
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

## 加上縮圖分析

如果你想讓工具也看影片縮圖，可以加上 `--visuals`：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --target-duration 180 \
  --visuals \
  --vision-model qwen2.5vl:7b
```

這裡的 `qwen2.5vl:7b` 是看圖片用的模型。

## 使用本機 AI 幫文字片段打分

如果你想讓 Ollama 幫文字片段打分：

```bash
uv run python auto_highlight.py run input.mp4 \
  --out work/video1 \
  --target-duration 180 \
  --planner ollama \
  --model qwen3:1.7b
```

這裡的 `qwen3:1.7b` 是看文字用的模型。

## 分段執行

如果影片很長，建議分段跑。這樣中途失敗時，不用全部重來。

```bash
uv run python auto_highlight.py prepare input.mp4 --out work/video1
uv run python auto_highlight.py analyze-visuals work/video1 --vision-model qwen2.5vl:7b
uv run python auto_highlight.py score work/video1 --planner heuristic
uv run python auto_highlight.py plan work/video1 --target-duration 180
uv run python auto_highlight.py render work/video1
```

每一步在做什麼：

| 步驟 | 指令 | 白話說明 |
| --- | --- | --- |
| 1 | `prepare` | 把影片聲音拿出來，產生逐字稿 |
| 2 | `analyze-visuals` | 抽縮圖，讓模型描述畫面 |
| 3 | `score` | 幫候選片段打分數 |
| 4 | `plan` | 決定最後要剪哪些片段 |
| 5 | `render` | 真的輸出精華影片 |

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
  review_report.md
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
| `output/highlight.mp4` | 成品 | 最後的精華影片 |

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
- API key
- 模型快取

這些通常會放在 `work/` 裡，而且 `.gitignore` 已經設定好不要上傳。

## 授權

本專案使用 MIT License。詳情請看 `LICENSE`。
