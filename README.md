# podcast-transcripts

用 `uv` 管理的 Podcast 逐字稿 / 摘要專案。

## 目前目錄結構

- `summaries/`: 每集正式摘要（最常看的輸出）
- `transcripts/raw/`: 原始 ASR JSON 或平台原始輸出
- `transcripts/clean/`: 整理後可讀版本（Markdown）
- `metadata/episodes/`: 每集 metadata
- `metadata/reviews/`: 不確定詞清單與複核檔
- `metadata/runs/`: 執行狀態檔
- `scripts/`: 抓取 / 轉錄 / 整理腳本

## 設計原則

1. **summary 是第一級產物**
   - 之後最常回看的內容應該是 `summaries/`
   - 所以摘要不再放在 `metadata/` 裡

2. **transcript / metadata / review 分層保存**
   - transcript 是原料
   - metadata 是結構化資訊
   - review 是校對輔助
   - summary 是最終可讀成品

3. **不保留 mp3 音檔**
   - 目前 workflow 不把音訊當成專案長期產物
   - 只保留 raw transcript、clean transcript、metadata、review、summary

## 單集流程（建議）

先複製 `.env.example` 成 `.env`，把專案路徑與節目設定填進去。

```bash
cd /path/to/podcast-transcripts
cp .env.example .env
uv run python scripts/process_episode.py --show gooaye --episode-number 656
```

這支 wrapper 現在只負責：
1. 依 `.env` 設定找到 feed / show slug
2. 必要時轉錄指定單集
3. 產出 / 更新 `metadata/episodes/` 的該集 metadata
4. 產出 `metadata/reviews/<base>-uncertain-terms.json`
5. 告訴你這集正式摘要應放的路徑：`summaries/<base>-summary.md`

### 重要

`process_episode.py` **不再自動生成 placeholder summary**。

原因：
- placeholder 容易讓人誤判為已完成
- 正式摘要需要依最新規格人工 / AI 整理
- 摘要格式會持續演進（例如股票分市場列表、5 分鐘可讀完等）

## 既有 transcript 上重建 review（不重跑 Whisper）

```bash
uv run python scripts/process_episode.py --show gooaye --episode-number 656 --skip-transcribe
```

## 摘要寫作規格（目前）

每集摘要預設：
1. metadata header
2. `提到的股票 / 公司`
   - 台股
   - 美股
   - 日股
   - 韓股
   - 中國
   - 其他
3. 4–6 個主題 section
4. 一句話總結

風格原則：
- 參考 EP654
- 有結構、分段清楚
- 約 5 分鐘內可讀完
- 不要過短像 memo
- 也不要寫成過長作文

## 批次轉錄 RSS Podcast

```bash
cd /path/to/podcast-transcripts
uv run python scripts/transcribe_rss_feed.py \
  --feed-url "$GOOAYE_FEED_URL" \
  --show-slug gooaye \
  --limit 10
```

## 公開 repo 注意事項

- `.env` 不提交
- `.env.example` 只放 placeholder
- transcript / metadata / run status 不應寫入本地絕對路徑
- feed URL 只作執行期使用，不應散落在公開 artifact 中
