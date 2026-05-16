from flask import Flask
import requests
import feedparser
import os
import threading
import time

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

RSS_URL = "https://www.stocktitan.net/news/rss.xml"

seen_links = set()

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN or CHAT_ID missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": False
        }, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)

def news_worker():
    while True:
        try:
            feed = feedparser.parse(RSS_URL)

            for entry in feed.entries[:10]:
                title = entry.get("title", "")
                link = entry.get("link", "")

                if not link or link in seen_links:
                    continue

                seen_links.add(link)

                message = f"🚨 StockTitan News\n\n{title}\n\n{link}"
                send_telegram(message)

        except Exception as e:
            print("News worker error:", e)

        time.sleep(30)

@app.route("/")
def home():
    return "stock-news-bot is running"

@app.route("/test")
def test():
    send_telegram("✅ stock-news-bot test message")
    return "test sent"

threading.Thread(target=news_worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
