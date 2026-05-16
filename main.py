from flask import Flask
import requests
import feedparser
import os
import threading
import time
import json
from openai import OpenAI

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

RSS_URL = "https://www.stocktitan.net/news/today/rss.xml"

client = OpenAI(api_key=OPENAI_API_KEY)

seen_links = set()

MIN_SCORE = 7

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

def analyze_news(title, link):
    if not OPENAI_API_KEY:
        return {
            "score": 0,
            "sentiment": "unknown",
            "reason": "OPENAI_API_KEY missing",
            "action": "skip"
        }

    prompt = f"""
你是美股事件驱动交易员，专门分析短线新闻是否可能引发股价大幅波动。

请分析下面这条 StockTitan 新闻，只输出 JSON，不要输出其它文字。

评分标准：
0-3 = 垃圾新闻/无交易价值
4-6 = 普通新闻/可看可不看
7-8 = 值得推送，可能引起明显波动
9-10 = 极强新闻，可能暴涨/暴跌/逼空

重点提高评分的新闻：
- 上调 guidance
- 财报大超预期
- 大订单
- NVIDIA / Microsoft / Amazon / hyperscaler 合作
- FDA approval / phase 3 成功
- buyout / acquisition / strategic alternatives
- 回购
- 短线可能引发逼空
- 小市值公司出现重大利好

重点降低评分的新闻：
- 会议演讲
- 普通任命
- 无金额合作
- 常规展示
- 普通 PR
- 无实质内容新闻

新闻标题：
{title}

新闻链接：
{link}

请严格返回这个 JSON 格式：
{{
  "score": 0,
  "sentiment": "bullish/bearish/neutral",
  "reason": "一句话说明为什么",
  "action": "push/skip"
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        data = json.loads(content)

        return {
            "score": int(data.get("score", 0)),
            "sentiment": data.get("sentiment", "neutral"),
            "reason": data.get("reason", ""),
            "action": data.get("action", "skip")
        }

    except Exception as e:
        print("AI analysis error:", e)
        return {
            "score": 0,
            "sentiment": "unknown",
            "reason": f"AI分析失败: {e}",
            "action": "skip"
        }

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

                analysis = analyze_news(title, link)
                score = analysis.get("score", 0)

                print(f"Checked: {title} | Score: {score}")

                if score >= MIN_SCORE and analysis.get("action") == "push":
                    message = (
                        f"🚨 高价值 StockTitan 新闻\n\n"
                        f"评分：{score}/10\n"
                        f"方向：{analysis.get('sentiment')}\n"
                        f"原因：{analysis.get('reason')}\n\n"
                        f"标题：{title}\n\n"
                        f"{link}"
                    )
                    send_telegram(message)

        except Exception as e:
            print("News worker error:", e)

        time.sleep(10)

@app.route("/")
def home():
    return "stock-news-bot with AI filter is running"

@app.route("/test")
def test():
    send_telegram("✅ stock-news-bot AI version test message")
    return "test sent"

@app.route("/latest")
def latest():
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        return "No news found from RSS."

    items = []
    for entry in feed.entries[:5]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        analysis = analyze_news(title, link)

        items.append(
            f"<b>{title}</b><br>"
            f"Score: {analysis.get('score')}/10<br>"
            f"Sentiment: {analysis.get('sentiment')}<br>"
            f"Reason: {analysis.get('reason')}<br>"
            f"<a href=' '>{link}</a ><br><br>"
        )

    return "<h3>Latest StockTitan News AI Analysis</h3>" + "".join(items)

threading.Thread(target=news_worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
