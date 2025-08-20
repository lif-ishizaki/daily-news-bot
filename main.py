import os
import json
import datetime
import feedparser
import requests
from newspaper import Article
import time

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
OPENROUTER_API_KEY  = os.environ["OPENROUTER_API_KEY"]

FEED_URLS = [
    "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
    "https://news.yahoo.co.jp/rss/categories/it.xml"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "posted.json")

def load_posted() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_posted(posted: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(posted), f, ensure_ascii=False, indent=2)

def get_hatena_count(url: str) -> int:
    api = f"https://api.b.st-hatena.com/entry.count?url={url}"
    try:
        r = requests.get(api, timeout=5)
        return int(r.text) if r.ok and r.text.isdigit() else 0
    except:
        return 0

def fetch_all_entries():
    entries = []
    for url in FEED_URLS:
        feed = feedparser.parse(url)
        for e in feed.entries:
            entries.append({
                "title": e.title,
                "link": e.link,
                "hatena": get_hatena_count(e.link)
            })
    return entries

def summarize(text: str, max_retries: int = 3) -> str:
    system_prompt = (
        "あなたは日本の新聞社で10年以上働くベテラン編集者です。"
        "読者が3分で理解できるように、記事本文を要点だけ抽出してください。"
        "出力は300字以内の自然な日本語で、主語の省略を避け、時制を統一してください。"
    )

    # テキストが長すぎる場合は先頭部分のみを使用
    if len(text) > 3000:
        text = text[:3000]

    for attempt in range(max_retries):
        try:
            print(f"API呼び出し試行 {attempt + 1}/{max_retries}")
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type":  "application/json",
                },
                data=json.dumps({
                    "model": "shisa-ai/shisa-v2-llama3.3-70b:free",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": text}
                    ],
                    "max_tokens": 240,
                }),
                timeout=60,  # タイムアウトを長くする
                stream=False  # ストリーミングを無効にする
            )
            resp.raise_for_status()
            summary = resp.json()["choices"][0]["message"]["content"]
            return summary.strip()

        except (requests.exceptions.ChunkedEncodingError, 
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.RequestException) as e:
            print(f"API呼び出しエラー (試行 {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 指数バックオフ
                print(f"{wait_time}秒待機してからリトライします...")
                time.sleep(wait_time)
            else:
                print("すべてのリトライが失敗しました。デフォルトの要約を返します。")
                return "記事の要約を取得できませんでした。元記事をご確認ください。"


def notify_slack(items) -> bool:
    try:
        today = datetime.date.today().strftime("%Y-%m-%d")
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"📰 *本日のITニュースまとめ({today})*\n"
                }
            },
            {"type": "divider"}
        ]
        for idx, it in enumerate(items, start=1):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*<{it['link']}|{it['title']}>*\n"
                        f"> はてなブックマーク数： {it['hatena']}\n"
                        f"> AI要約： {it['summary']}"
                    )
                }
            })
            blocks.append({"type": "divider"})
        payload = {
            "blocks": blocks,
            "unfurl_links": False,
            "unfurl_media": False
        }
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Slack通知でエラーが発生しました: {e}")
        return False

def main():
    print("ニュースボットを開始します...")
    posted      = load_posted()
    print(f"既に投稿済みの記事数: {len(posted)}")

    print("RSSフィードから記事を取得中...")
    all_entries = fetch_all_entries()
    print(f"取得した記事数: {len(all_entries)}")

    candidates  = [e for e in all_entries if e["link"] not in posted]
    new_entries = sorted(candidates, key=lambda x: x["hatena"], reverse=True)[:3]
    print(f"新しい記事数: {len(candidates)}, 上位3件を処理します")

    if not new_entries:
        print("新しい記事がありません。")
        return

    results = []
    for idx, e in enumerate(new_entries, 1):
        print(f"\n[{idx}/3] 記事を処理中: {e['title'][:50]}...")
        try:
            art = Article(e["link"])
            art.download()
            art.parse()

            if not art.text or len(art.text.strip()) < 100:
                print(f"記事の本文が短すぎるかダウンロードに失敗しました: {e['link']}")
                summary = "記事の内容を取得できませんでした。"
            else:
                print(f"記事の本文を取得しました (文字数: {len(art.text)})")
                summary = summarize(art.text)

            results.append({**e, "summary": summary})
            posted.add(e["link"])
            print(f"処理完了: はてブ数 {e['hatena']}")

        except Exception as ex:
            print(f"記事の処理中にエラーが発生しました: {ex}")
            print(f"スキップします: {e['link']}")
            # エラーが発生した記事もスキップして続行
            results.append({**e, "summary": "記事の処理中にエラーが発生しました。"})
            posted.add(e["link"])

    if results:
        print(f"\nSlackに{len(results)}件の記事を送信中...")
        success = notify_slack(results)
        if success:
            print("Slackへの送信が完了しました。")
        else:
            print("Slackへの送信に失敗しました。")
        save_posted(posted)
        print("状態を保存しました。")
    else:
        print("送信する記事がありません。")

if __name__ == "__main__":
    main()