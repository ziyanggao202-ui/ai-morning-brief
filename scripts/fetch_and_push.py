#!/usr/bin/env python3
"""
AI Morning Brief - Cloud News Fetcher & WeChat Pusher
Replacement for local automation, designed to run in GitHub Actions.
Fetches news via RSS feeds, formats as Markdown, pushes via ServerChan.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os
import re
import textwrap
from datetime import datetime, timezone, timedelta
from html import unescape

# ── Configuration ──────────────────────────────────────────────
SENDKEY = os.environ.get("SENDKEY", "")
if not SENDKEY:
    raise ValueError("SENDKEY environment variable is not set")

# Beijing time
BJ_TZ = timezone(timedelta(hours=8))
NOW = datetime.now(BJ_TZ)
DATE_LABEL = NOW.strftime("%Y年%m月%d日")
DATE_ISO = NOW.strftime("%Y-%m-%d")
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY = WEEKDAY_CN[NOW.weekday()]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

NEWS_QUERIES = {
    "ai": {
        "tag": "AI领袖",
        "queries": [
            "AI+人工智能+大模型",
            "OpenAI+ChatGPT+AI",
        ],
    },
    "robot": {
        "tag": "机器人",
        "queries": [
            "机器人+人形机器人",
            "机器人+AI+自动化",
        ],
    },
    "finance": {
        "tag": "泛金融",
        "queries": [
            "金融+股市+经济",
            "A股+港股+美股",
        ],
    },
}

MAX_ITEMS_PER_CATEGORY = 8
TIMEOUT = 15


# ── News Fetching ──────────────────────────────────────────────
def fetch_rss(url: str) -> str | None:
    """Fetch RSS feed, return XML string or None."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            # Detect encoding
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            return data.decode(charset, errors="replace")
    except Exception as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None


def parse_rss_items(xml_str: str, max_items: int = 10) -> list[dict]:
    """Parse RSS XML into list of {title, link, pubDate, source, description}."""
    items = []
    try:
        root = ET.fromstring(xml_str)
        # RSS 2.0: /rss/channel/item
        for item in root.iter("item"):
            title = ""
            link = ""
            pub_date = ""
            source = ""
            description = ""

            for child in item:
                tag = child.tag.split("}")[-1]  # remove namespace
                if tag == "title":
                    title = unescape(child.text or "")
                elif tag == "link":
                    link = (child.text or "").strip()
                elif tag == "pubDate":
                    pub_date = child.text or ""
                elif tag == "source":
                    source = child.text or ""
                elif tag == "description":
                    description = unescape(
                        re.sub(r"<[^>]+>", "", child.text or "")
                    )

            if title:
                # Clean up Google News prefixes like "title - source"
                title = title.strip()
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pub_date,
                    "source": source,
                    "description": description[:200],
                })

        return items[:max_items]
    except ET.ParseError as e:
        print(f"[WARN] XML parse error: {e}")
        return []


def search_google_news(query: str, max_items: int = 5) -> list[dict]:
    """Search Google News RSS by keyword."""
    url = (
        f"https://news.google.com/rss/search?"
        f"q={urllib.parse.quote(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )
    xml_str = fetch_rss(url)
    if not xml_str:
        return []
    return parse_rss_items(xml_str, max_items)


def format_pub_date(date_str: str) -> str:
    """Format RSS pubDate to relative time."""
    if not date_str:
        return ""
    try:
        # RFC 2822 format
        dt = datetime.strptime(
            date_str[:25].strip(), "%a, %d %b %Y %H:%M:%S"
        )
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return date_str[:16] if len(date_str) > 16 else date_str


def collect_news() -> dict:
    """Collect news from all categories. Returns {category: [items]}."""
    all_news = {}

    for category, config in NEWS_QUERIES.items():
        seen_titles = set()
        cat_items = []

        for query in config["queries"]:
            results = search_google_news(query, max_items=6)
            for item in results:
                # Deduplicate
                title_key = item["title"][:40]
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    cat_items.append(item)

            if len(cat_items) >= MAX_ITEMS_PER_CATEGORY:
                break

        # Sort by date (newest first) if available
        cat_items = cat_items[:MAX_ITEMS_PER_CATEGORY]
        all_news[category] = cat_items

    return all_news


# ── Markdown Formatting ────────────────────────────────────────
def build_markdown(all_news: dict) -> tuple[str, str]:
    """Build title and markdown body for WeChat push."""

    # Highlights
    highlights = []
    for category, items in all_news.items():
        if items:
            title = items[0]["title"]
            # Truncate for highlights
            if len(title) > 30:
                title = title[:28] + "…"
            highlights.append(title)

    if len(highlights) < 3:
        # Add from other categories
        for category, items in all_news.items():
            if len(highlights) >= 3:
                break
            for item in items[1:]:
                if len(highlights) >= 3:
                    break
                title = item["title"]
                if len(title) > 30:
                    title = title[:28] + "…"
                highlights.append(title)

    title = f"AI早报 · {DATE_LABEL}"

    lines = [f"# 今日要点\n"]
    for h in highlights[:3]:
        lines.append(f"- {h}")

    # Category sections
    category_names = {
        "ai": "AI领袖动态",
        "robot": "机器人全赛道",
        "finance": "泛金融新闻",
    }

    for category, display_name in category_names.items():
        items = all_news.get(category, [])
        if not items:
            continue

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"# {display_name}")
        lines.append("")

        for idx, item in enumerate(items, 1):
            title_text = item["title"]
            desc = item["description"][:200] if item["description"] else ""
            source_text = item["source"] if item["source"] else "Google News"
            time_text = format_pub_date(item["pubDate"])

            lines.append(f"## {idx}. {title_text}")
            lines.append("")
            if desc:
                lines.append(f"{desc}")
                lines.append("")
            source_line = f"来源：{source_text}"
            if time_text:
                source_line += f" · {time_text}"
            lines.append(f"*{source_line}*")
            lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        f"🤖 由 GitHub Actions 自动生成 · {DATE_LABEL} {WEEKDAY}"
    )
    lines.append("")
    lines.append(
        "📱 完整版含播客音频，请访问本地 AI早报应用"
    )
    lines.append("")
    lines.append("— Eric的AI每日早报 —")

    body = "\n".join(lines)
    return title, body


# ── Push ───────────────────────────────────────────────────────
def push_to_wechat(title: str, content: str) -> dict:
    """Send to ServerChan."""
    url = f"https://sctapi.ftqq.com/{SENDKEY}.send"
    data = urllib.parse.urlencode({
        "title": title,
        "desp": content,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result
    except Exception as e:
        return {"code": -1, "error": str(e)}


# ── Main ───────────────────────────────────────────────────────
def main():
    print(f"🚀 AI Morning Brief · {DATE_LABEL} {WEEKDAY}")
    print(f"⏰ Started at {NOW.strftime('%H:%M:%S')}")
    print()

    # Step 1: Collect news
    print("📡 Step 1: Collecting news...")
    all_news = collect_news()

    total = sum(len(items) for items in all_news.values())
    for cat, items in all_news.items():
        print(f"   {cat}: {len(items)} articles")
    print(f"   Total: {total} articles")
    print()

    if total == 0:
        print("❌ No news collected, sending fallback push")
        title = f"AI早报 · {DATE_LABEL}"
        body = (
            f"# AI早报 · {DATE_LABEL}\n\n"
            f"⚠️ 今日新闻采集未获取到内容，请检查脚本或稍后重试。\n\n"
            f"— Eric的AI每日早报 —"
        )
    else:
        # Step 2: Build markdown
        print("📝 Step 2: Building markdown...")
        title, body = build_markdown(all_news)
        print(f"   Title: {title}")
        print(f"   Body length: {len(body)} chars")
        print()

    # Step 3: Push
    print(f"📱 Step 3: Pushing to WeChat...")
    result = push_to_wechat(title, body)

    if result.get("code") == 0:
        print(f"✅ Push successful! Message ID: {result.get('message_id', 'N/A')}")
        print(f"   WeChat push ID: {result.get('weixin_push_id', 'N/A')}")
    else:
        print(f"❌ Push failed: {result.get('error', 'Unknown error')}")
        print(f"   Full response: {json.dumps(result, ensure_ascii=False)}")

    # Print summary
    print()
    print("📊 Summary:")
    for cat, items in all_news.items():
        print(f"   [{cat}] {len(items)} articles")
        for item in items:
            print(f"       - {item['title'][:60]}")
    print()
    print(f"✨ Done at {datetime.now(BJ_TZ).strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
