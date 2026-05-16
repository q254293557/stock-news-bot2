from flask import Flask
import requests
from bs4 import BeautifulSoup
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

NEWS_URL = "https://www.stocktitan.net/news/live.html"

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
