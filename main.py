from flask import Flask
import requests
from bs4 import BeautifulSoup
import os
import threading
import time
import json
from openai import OpenAI

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

NEWS_URL = "https://www.stocktitan.net/news/live.html"

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

def fetch_latest_news():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(NEWS_URL, headers=headers, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        title = " ".join(a.get_text(" ", strip=True).split())

        if not title:
            continue

        if "/news/" not in href:
            continue

        if href.startswith("/"):
            link = "https://www.stocktitan.net" + href
        else:
            link = href

        if "stocktitan.net/news/" not in link:
            continue

        if len(title) < 20:
            continue

        item = {
            "title": title,
            "link": link
        }

        if item not in results:
            results.append(item)

        if len(results) >= 10:
            break

    return results

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
- 大额融资
- 债务重组成功
- 重大合同
- 监管批准

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
            model="gpt-4.1-mini",
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
            news_items = fetch_latest_news()

            for item in news_items:
                title = item["title"]
                link = item["link"]

                if link in seen_links:
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
    return "stock-news-bot with AI webpage filter is running"

@app.route("/test")
def test():
    send_telegram("✅ stock-news-bot AI webpage version test message")
    return "test sent"

@app.route("/latest")
def latest():
    try:
        news_items = fetch_latest_news()

        if not news_items:
            return "No news found from StockTitan webpage."

        items = []
        for item in news_items[:5]:
            title = item["title"]
            link = item["link"]
            analysis = analyze_news(title, link)

            items.append(
                f"<b>{title}</b><br>"
                f"Score: {analysis.get('score')}/10<br>"
                f"Sentiment: {analysis.get('sentiment')}<br>"
                f"Reason: {analysis.get('reason')}<br>"
                f"<a href=' '>{link}</a ><br><br>"
            )

        return "<h3>Latest StockTitan News AI Analysis</h3>" + "".join(items)

    except Exception as e:
        return f"Error: {e}"

threading.Thread(target=news_worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
