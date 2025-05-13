# IT News Digest Slack Notifier
日本のITニュースを収集・要約し、Slackに毎朝自動投稿するツール

## 機能概要
- ITmedia および Yahoo!ニュース（ITカテゴリ）からRSSを取得
- 各記事の「はてなブックマーク数」で注目度を判定
- 上位3件の記事を `transformers` によるAI要約
- Slack Webhook経由で投稿
