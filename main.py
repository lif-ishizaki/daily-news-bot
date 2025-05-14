import os
import json
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

def summarize(text: str) -> str:
    if not hasattr(summarize, "pipe"):
        model_name = "tsmatz/mt5_summarize_japanese"
        summarize.pipe = pipeline(
            "summarization",
            model=model_name,
            tokenizer=model_name,
            framework="pt",
            device=-1,
        )

    prompt = (
        "以下の記事を200〜300文字程度で要約してください。"\
        "事実を追加・改変せず、重要な数値・固有名詞は保持してください。" + text
    )

    tokens = summarize.pipe.tokenizer.encode(prompt, return_tensors="pt")
    max_len = min(240, int(len(tokens[0]) * 0.25)) or 120
    min_len = int(max_len * 0.6)

    result = summarize.pipe(
        prompt,
        max_length=max_len,
        min_length=min_len,
        num_beams=10,
        no_repeat_ngram_size=3,
        length_penalty=1.2,
        repetition_penalty=1.05,
        early_stopping=True,
        do_sample=False,
    )
    return result[0]["summary_text"].strip()


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
    posted      = load_posted()
    all_entries = fetch_all_entries()

    candidates  = [e for e in all_entries if e["link"] not in posted]
    new_entries = sorted(candidates, key=lambda x: x["hatena"], reverse=True)[:3]

    if not new_entries:
        print("No new items to post.")
        return

    results = []
    for e in new_entries:
        art = Article(e["link"])
        art.download()
        art.parse()
        summary = summarize(art.text)
        results.append({**e, "summary": summary})
        posted.add(e["link"])
    notify_slack(results)
    save_posted(posted)

if __name__ == "__main__":
    main()
