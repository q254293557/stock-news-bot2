from flask import Flask
import requests
from bs4 import BeautifulSoup
import feedparser
import os
import threading
import time
import json
from datetime import date
from openai import OpenAI

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

NEWS_URL = "https://www.stocktitan.net/rss"

client = OpenAI(api_key=OPENAI_API_KEY)

seen_links = set()

MIN_SCORE = 7
MAX_AI_ANALYSIS_PER_DAY = 100

daily_ai_count = 0
daily_count_date = date.today()

KEYWORDS = [
    "AI", "artificial intelligence", "machine learning",
    "semiconductor", "chip", "chips", "GPU", "NVIDIA", "NVDA",
    "data center", "datacenter", "hyperscale", "hyperscaler",
    "optical", "photonics", "silicon photonics",
    "CPO", "co-packaged optics",
    "transceiver", "optical module", "fiber optic",
    "800G", "1.6T", "400G",
    "laser", "VCSEL",
    "pluggable", "ethernet",
    "inference", "accelerator",
    "AI infrastructure", "networking", "switching",
    "compute", "cloud", "server",

    "robotics", "robot", "automation", "autonomous",
    "autonomous driving", "self-driving",
    "ADAS", "lidar", "LiDAR",
    "drone", "drones", "UAV",
    "industrial automation",

    "defense", "military", "aerospace",
    "space", "satellite", "satellites",
    "launch", "rocket", "spacecraft",
    "missile", "radar", "surveillance",
    "government contract", "department of defense", "DoD",

    "nuclear", "SMR", "small modular reactor",
    "uranium", "reactor",
    "power grid", "grid", "electricity",
    "energy storage", "battery storage",
    "clean energy", "renewable energy",

    "bitcoin", "BTC", "crypto", "cryptocurrency",
    "blockchain", "stablecoin", "digital asset",
    "mining", "bitcoin mining",
    "fintech", "payments", "payment platform",

    "quantum", "quantum computing",
    "cybersecurity", "cyber security",
    "cloud", "SaaS", "software",
    "zero trust", "identity security",

    "FDA", "approval", "clearance",
    "phase 3", "phase III", "phase 2", "phase II",
    "clinical trial", "primary endpoint",
    "biotech", "pharmaceutical",
    "drug", "therapy", "treatment",
    "GLP-1", "obesity", "diabetes",
    "oncology", "cancer",

    "lithium", "battery", "batteries",
    "solid-state battery",
    "rare earth", "copper", "gold", "silver",
    "mining", "critical minerals",

    "earnings", "results", "financial results",
    "quarterly results", "q1 results", "q2 results", "q3 results", "q4 results",
    "revenue", "revenues", "sales",
    "EPS", "earnings per share",
    "beat", "beats", "exceeds", "exceeded", "above expectations",
    "raises guidance", "raise guidance", "raised guidance",
    "guidance", "outlook", "forecast",
    "record revenue", "record revenues",
    "profit", "margin", "gross margin",

    "contract", "major contract", "award",
    "partnership", "strategic partnership",
    "collaboration", "customer win",
    "backlog", "order", "orders",
    "acquisition", "merger", "buyout",
    "takeover", "strategic alternatives",
    "tender offer",
    "share repurchase", "buyback"
]

LOW_VALUE_WORDS = [
    "conference", "webcast", "presentation",
    "appoints", "appointment", "management change",
    "to participate", "investor conference",
    "announces date", "earnings call",
    "shareholder meeting",
    "fireside chat", "annual meeting",
    "to present at", "will attend"
]


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN or CHAT_ID missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
    except Exception as e:
        print("Telegram send error:", e)


def reset_daily_counter_if_needed():
    global daily_ai_count, daily_count_date

    today = date.today()
    if today != daily_count_date:
        daily_count_date = today
        daily_ai_count = 0


def keyword_match(text):
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in KEYWORDS)


def low_value_match(text):
    text_lower = text.lower()

    earnings_terms = [
        "reports",
        "reported",
        "financial results",
        "quarterly results",
        "revenue",
        "eps",
        "raises guidance",
        "raised guidance",
        "beats",
        "exceeds",
        "record revenue",
        "announces record",
        "strong outlook",
    ]

    if any(term in text_lower for term in earnings_terms):
        return False

    return any(word.lower() in text_lower for word in LOW_VALUE_WORDS)


def fetch_latest_news():
    feed = feedparser.parse(NEWS_URL)

    results = []

    for entry in feed.entries[:30]:
        title = entry.get("title", "")
        link = entry.get("link", "")

        title = " ".join(title.split())
        link = link.strip()

        if not title or not link:
            continue

        item = {"title": title, "link": link}

        if item not in results:
            results.append(item)

    return results


def fetch_article_text(link):
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(link, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join(soup.get_text(" ", strip=True).split())
        return text[:7000]

    except Exception as e:
        print("Article fetch error:", e)
        return ""


def is_nasdaq_article(title, article_text):
    text_lower = f"{title} {article_text}".lower()

    if "nasdaq:" in text_lower:
        return True

    if "nasdaq capital market" in text_lower:
        return True

    if "nasdaqcm" in text_lower:
        return True

    if "nasdaqgs" in text_lower:
        return True

    if "nasdaqgm" in text_lower:
        return True

    return False


def pre_filter_news(title, article_text):
    combined = f"{title} {article_text}"

    if low_value_match(combined):
        return False, "低价值新闻，跳过，不消耗 AI 额度"

    if not keyword_match(combined):
        return False, "不属于热门板块 / 财报超预期 / 大单并购方向，跳过"

    if not is_nasdaq_article(title, article_text):
        return False, "不是 NASDAQ 股票新闻，跳过"

    return True, "通过预筛选"


def analyze_news(title, link, article_text):
    global daily_ai_count

    reset_daily_counter_if_needed()

    if daily_ai_count >= MAX_AI_ANALYSIS_PER_DAY:
        return {
            "score": 0,
            "sentiment": "unknown",
            "sector": "unknown",
            "is_nasdaq": False,
            "market_cap_usd": "unknown",
            "move_potential": "unknown",
            "earnings_surprise": "unknown",
            "reason": f"今日 AI 分析已达上限 {MAX_AI_ANALYSIS_PER_DAY} 条，跳过",
            "action": "skip",
        }

    if not OPENAI_API_KEY:
        return {
            "score": 0,
            "sentiment": "unknown",
            "sector": "unknown",
            "is_nasdaq": False,
            "market_cap_usd": "unknown",
            "move_potential": "unknown",
            "earnings_surprise": "unknown",
            "reason": "OPENAI_API_KEY missing",
            "action": "skip",
        }

    daily_ai_count += 1

    prompt = f"""
你是美股事件驱动交易员，专门筛选短线可能大涨的 NASDAQ 股票新闻。

目标：
只推送 NASDAQ 上市公司中，市值 10 亿美元及以上，并且属于热门板块或财报超预期的高价值新闻。

热门板块包括：
AI、半导体、光模块、CPO、数据中心、机器人、自动驾驶、无人机、国防军工、航天卫星、核能、铀矿、电力、储能、加密货币、区块链、金融科技、量子计算、网络安全、云计算、生物医药、FDA、临床三期、GLP-1、锂电池、稀土、铜、黄金、重大并购、大订单、回购、财报超预期、guidance 上调。

硬性推送条件：
1. 必须是 NASDAQ 上市公司；
2. 估算市值必须在 10 亿美元及以上，也就是 market_cap_usd 必须返回 ">=1B"；
3. 新闻必须属于热门板块、财报超预期、guidance 上调、大订单、并购、回购、重大合同其中之一；
4. 评分必须 >= 7；
5. 短线暴涨潜力必须是 high 或 medium；
6. 满足以上条件才 action = "push"，否则 action = "skip"。

评分标准：
0-3 = 垃圾新闻 / 无交易价值
4-6 = 普通新闻 / 不推送
7-8 = 值得推送，可能引起明显波动
9-10 = 极强新闻，可能暴涨 / 逼空 / 连续拉升

重点提高评分：
- 财报大幅超预期
- EPS beat + revenue beat
- 上调全年 guidance
- record revenue
- 毛利率明显改善
- backlog 明显增长
- AI 数据中心订单
- 大额订单
- 大客户合作
- NVIDIA / Microsoft / Amazon / Google / Meta / hyperscaler 合作
- 半导体产品进入量产
- 光模块 / CPO / 硅光 / 800G / 1.6T 相关重大进展
- 机器人 / 自动驾驶 / 无人机 / 国防 / 航天 / 核能 / 量子 / 加密货币 / 生物医药等热门板块重大进展
- FDA approval / phase 3 成功 / primary endpoint met
- 大金额融资
- buyout / acquisition / tender offer / strategic alternatives
- 10 亿美元以上但仍容易异动的中小市值 NASDAQ 公司

重点降低评分：
- 只是公布财报日期
- 只是 earnings call 通知
- 会议演讲
- 普通任命
- 没金额的合作
- 常规展示
- 普通 PR
- 市值低于 10 亿美元
- 大盘成熟公司但催化不强
- 业绩 beat 但 guidance 下调
- 收入增长弱、亏损扩大、现金流恶化
- 和热门板块无关

新闻标题：
{title}

新闻链接：
{link}

新闻正文节选：
{article_text[:4000]}

请严格返回 JSON，不要输出任何多余文字：
{{
  "score": 0,
  "sentiment": "bullish/bearish/neutral",
  "sector": "AI/semiconductor/optical/CPO/datacenter/robotics/autonomous/defense/space/nuclear/crypto/quantum/cybersecurity/biotech/energy/metals/earnings/M&A/other",
  "is_nasdaq": true,
  "market_cap_usd": ">=1B/<1B/unknown",
  "move_potential": "high/medium/low/unknown",
  "earnings_surprise": "strong/medium/weak/none/unknown",
  "reason": "一句话说明为什么值得或不值得推送",
  "action": "push/skip"
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()

        data = json.loads(content)

        return {
            "score": int(data.get("score", 0)),
            "sentiment": data.get("sentiment", "neutral"),
            "sector": data.get("sector", "other"),
            "is_nasdaq": data.get("is_nasdaq", False),
            "market_cap_usd": data.get("market_cap_usd", "unknown"),
            "move_potential": data.get("move_potential", "unknown"),
            "earnings_surprise": data.get("earnings_surprise", "unknown"),
            "reason": data.get("reason", ""),
            "action": data.get("action", "skip"),
        }

    except Exception as e:
        print("AI analysis error:", e)
        return {
            "score": 0,
            "sentiment": "unknown",
            "sector": "unknown",
            "is_nasdaq": False,
            "market_cap_usd": "unknown",
            "move_potential": "unknown",
            "earnings_surprise": "unknown",
            "reason": f"AI分析失败: {e}",
            "action": "skip",
        }


def should_push(analysis):
    score = analysis.get("score", 0)
    action = analysis.get("action", "skip")
    is_nasdaq = analysis.get("is_nasdaq", False)
    market_cap_usd = analysis.get("market_cap_usd", "unknown")
    move_potential = analysis.get("move_potential", "unknown")

    return (
        score >= MIN_SCORE
        and action == "push"
        and is_nasdaq is True
        and market_cap_usd == ">=1B"
        and move_potential in ["high", "medium"]
    )


def process_news_item(title, link):
    article_text = fetch_article_text(link)

    passed, filter_reason = pre_filter_news(title, article_text)

    if not passed:
        print(f"Skipped prefilter: {title} | {filter_reason}")
        return None

    analysis = analyze_news(title, link, article_text)

    print(
        f"Checked: {title} | "
        f"Score: {analysis.get('score')} | "
        f"NASDAQ: {analysis.get('is_nasdaq')} | "
        f"MarketCap: {analysis.get('market_cap_usd')} | "
        f"Move: {analysis.get('move_potential')} | "
        f"Action: {analysis.get('action')}"
    )

    if should_push(analysis):
        message = (
            f"🚨 NASDAQ 热门板块高价值新闻\n\n"
            f"评分：{analysis.get('score')}/10\n"
            f"方向：{analysis.get('sector')}\n"
            f"情绪：{analysis.get('sentiment')}\n"
            f"市值判断：{analysis.get('market_cap_usd')}\n"
            f"暴涨潜力：{analysis.get('move_potential')}\n"
            f"财报超预期：{analysis.get('earnings_surprise')}\n"
            f"原因：{analysis.get('reason')}\n\n"
            f"标题：{title}\n\n"
            f"{link}"
        )
        send_telegram(message)

    return analysis


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
                process_news_item(title, link)

        except Exception as e:
            print("News worker error:", e)

        time.sleep(10)


@app.route("/")
def home():
    return "stock-news-bot RSS NASDAQ >=1B hot sectors AI filter is running"


@app.route("/test")
def test():
    send_telegram("✅ stock-news-bot RSS NASDAQ >=1B hot sectors AI filter test message")
    return "test sent"


@app.route("/latest")
def latest():
    try:
        reset_daily_counter_if_needed()

        news_items = fetch_latest_news()

        if not news_items:
            return "No news found from StockTitan RSS."

        items = []

        for item in news_items[:10]:
            title = item["title"]
            link = item["link"]
            article_text = fetch_article_text(link)

            passed, filter_reason = pre_filter_news(title, article_text)

            if not passed:
                items.append(
                    f"<b>{title}</b><br>"
                    f"Pre-filter: SKIP<br>"
                    f"Reason: {filter_reason}<br>"
                    f"<a href='{link}'>{link}</a><br><br>"
                )
                continue

            analysis = analyze_news(title, link, article_text)

            items.append(
                f"<b>{title}</b><br>"
                f"Score: {analysis.get('score')}/10<br>"
                f"Sector: {analysis.get('sector')}<br>"
                f"Sentiment: {analysis.get('sentiment')}<br>"
                f"NASDAQ: {analysis.get('is_nasdaq')}<br>"
                f"Market cap: {analysis.get('market_cap_usd')}<br>"
                f"Move potential: {analysis.get('move_potential')}<br>"
                f"Earnings surprise: {analysis.get('earnings_surprise')}<br>"
                f"Action: {analysis.get('action')}<br>"
                f"Reason: {analysis.get('reason')}<br>"
                f"<a href='{link}'>{link}</a><br><br>"
            )

        return (
            f"<h3>StockTitan RSS NASDAQ >= $1B Hot Sectors AI Filter</h3>"
            f"<p>Daily AI used: {daily_ai_count}/{MAX_AI_ANALYSIS_PER_DAY}</p>"
            + "".join(items)
        )

    except Exception as e:
        return f"Error: {e}"


threading.Thread(target=news_worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
