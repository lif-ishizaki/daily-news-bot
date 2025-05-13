import os
import datetime
import feedparser
import requests
from newspaper import Article
from transformers import pipeline

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
FEED_URLS = [
    "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
    "https://news.yahoo.co.jp/rss/categories/it.xml"
]

def get_hatena_count(url: str) -> int:
    api = f"https://api.b.st-hatena.com/entry.count?url={url}"
    try:
        r = requests.get(api, timeout=5)
        return int(r.text) if r.ok and r.text.isdigit() else 0
    except:
        return 0

def fetch_entries():
    entries = []
    for url in FEED_URLS:
        feed = feedparser.parse(url)
        for e in feed.entries:
            count = get_hatena_count(e.link)
            entries.append({
                "title": e.title,
                "link": e.link,
                "hatena": count
            })
    return sorted(entries, key=lambda x: x["hatena"], reverse=True)[:3]

def summarize(text: str) -> str:
    if not hasattr(summarize, "pipe"):
        summarize.pipe = pipeline(
            "summarization",
            model="tsmatz/mt5_summarize_japanese",
            tokenizer="tsmatz/mt5_summarize_japanese",
            framework="pt",
            device=-1,
            max_length=256,
            min_length=120,
            do_sample=False,
            num_beams=4,
            length_penalty=2.0
        )
    result = summarize.pipe(text)
    return result[0]["summary_text"]

def notify_slack(items) -> bool:
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
    return resp.ok

def main():
    entries = fetch_entries()
    results = []
    for e in entries:
        art = Article(e["link"])
        art.download()
        art.parse()
        summary = summarize(art.text)
        results.append({**e, "summary": summary})
    notify_slack(results)

if __name__ == "__main__":
    main()