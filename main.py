import os
import json
import datetime
import feedparser
import requests
from newspaper import Article

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

def summarize(text: str) -> str:
    system_prompt = (
        "あなたは日本の新聞社で10年以上働くベテラン編集者です。"
        "読者が3分で理解できるように、記事本文を要点だけ抽出してください。"
        "出力は300字以内の自然な日本語で、主語の省略を避け、時制を統一してください。"
    )
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
        timeout=30,
    )
    resp.raise_for_status()
    summary = resp.json()["choices"][0]["message"]["content"]
    return summary.strip()


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
