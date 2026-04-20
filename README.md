# podcast-transcripts

用 `uv` 管理的 Podcast 逐字稿專案。

## 目錄

- `transcripts/raw/`: 原始 ASR JSON 或平台原始輸出
- `transcripts/clean/`: 整理後可讀版本（Markdown）
- `metadata/episodes/`: 每集 metadata
- `metadata/summaries/`: 每集摘要（Markdown）
- `metadata/reviews/`: 不確定詞清單與複核檔
- `metadata/runs/`: 批次/執行狀態檔
- `scripts/`: 抓取/轉錄腳本
- `audio/`: 選擇保留的音訊檔

## 批次轉錄 RSS Podcast

```bash
cd /path/to/podcast-transcripts
uv run python scripts/transcribe_rss_feed.py \
  --feed-url "$GOOAYE_FEED_URL" \
  --show-slug gooaye \
  --limit 10
```

## 單集統一流程（建議）

先複製 `.env.example` 成 `.env`，把專案路徑與節目設定放進 `.env`。`.env` 已加入 `.gitignore`，不會推上 GitHub。

```bash
cd /path/to/podcast-transcripts
cp .env.example .env  # 第一次使用時
# 然後把 .env 裡的路徑 / feed / show config 改成你自己的值
uv run python scripts/process_episode.py --show gooaye --episode-number 653
```

這支 wrapper 會：
1. 依 `.env` 設定找到 feed / show slug
2. 必要時轉錄指定單集
3. 產出 / 更新 `metadata/episodes/` 的該集 metadata
4. 產出 `metadata/reviews/<base>-uncertain-terms.json`
5. 產出 `metadata/summaries/<base>-summary.md`

補充：feed URL 只用於執行期抓資料，不會再寫進 repo 內的 transcript / metadata / run status 檔案，避免把來源設定散落到公開產物中。

預設不會覆蓋已存在的 `summary` / `uncertain-terms`，避免人工校修成果被蓋掉；如果你真的要重建草稿，請加：

```bash
uv run python scripts/process_episode.py --show gooaye --episode-number 653 --skip-transcribe --overwrite-artifacts
```

如果只想基於既有 transcript 重建 review / summary，不重跑 Whisper：

```bash
uv run python scripts/process_episode.py --show gooaye --episode-number 653 --skip-transcribe
```

## 舊腳本用途

腳本會：
1. 讀 RSS feed 最新集數
2. 下載音訊
3. 用本機 `openai-whisper`（透過 `uvx`）轉錄
4. 存成 raw JSON / clean Markdown / metadata JSON（放在 `metadata/episodes/`）
5. 將最近一次批次狀態寫到 `metadata/runs/<show-slug>-last-run.json`
