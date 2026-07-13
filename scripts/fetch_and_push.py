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
import base64
import sys
import re
import textwrap
from datetime import datetime, timezone, timedelta
from html import unescape

# Add repo root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or ".")
try:
    from scripts.generate_image import generate_image
    HAS_IMAGE = True
except ImportError:
    HAS_IMAGE = False

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
SITE_URL = "https://c5cc7d27723044f5aef17214f4055d1c.app.codebuddy.work"


def build_markdown(all_news: dict) -> tuple[str, str]:
    """Build compact title and body optimized for WeChat card preview."""

    # Collect headlines from all categories
    highlights = []
    total_count = 0
    for category, items in all_news.items():
        total_count += len(items)
        for item in items[:3]:  # top 3 from each
            title = item["title"]
            if len(title) > 35:
                title = title[:33] + "…"
            highlights.append(title)

    # Keep top 6 highlights max
    highlights = highlights[:6]

    # Count per category for the summary line
    ai_count = len(all_news.get("ai", []))
    robot_count = len(all_news.get("robot", []))
    finance_count = len(all_news.get("finance", []))

    title = f"AI早报 · {DATE_LABEL}"

    lines = []
    lines.append(f"AI领袖({ai_count}条) | 机器人({robot_count}条) | 泛金融({finance_count}条)")
    lines.append("━" * 22)
    lines.append("")

    for h in highlights:
        lines.append(f"▸ {h}")

    lines.append("")
    lines.append("━" * 22)
    lines.append("")
    lines.append(f"👉 点击查看完整早报（共{total_count}条新闻）")
    lines.append(SITE_URL)
    lines.append("")
    lines.append(f"每天早上8:00自动更新  ·  Eric的私人早报")

    body = "\n".join(lines)
    return title, body


# ── Push ───────────────────────────────────────────────────────
def push_to_wechat(title: str, content: str, image_url: str = "") -> dict:
    """Send to ServerChan with optional image."""
    url = f"https://sctapi.ftqq.com/{SENDKEY}.send"
    params = {
        "title": title,
        "desp": content,
        "short": content.split("\n")[0][:80],
    }
    if image_url:
        # Embed image in markdown
        params["desp"] = f"![早报]({image_url})\n\n{content}"

    data = urllib.parse.urlencode(params).encode("utf-8")

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
def upload_to_github(file_path: str, repo_path: str) -> str:
    """Upload file to GitHub repo, return raw URL."""
    TOKEN = os.environ.get("GITHUB_TOKEN", "")
    if not TOKEN:
        print("⚠️ No GITHUB_TOKEN, skipping upload")
        return ""

    REPO = "ziyanggao202-ui/ai-morning-brief"
    API = f"https://api.github.com/repos/{REPO}/contents/{repo_path}"

    with open(file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    # Check if file exists to get SHA
    try:
        req = urllib.request.Request(
            API,
            headers={
                "Authorization": f"token {TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            existing = json.loads(resp.read().decode())
            sha = existing.get("sha", "")
    except Exception:
        sha = ""

    # Upload
    data = json.dumps({
        "message": f"Update {repo_path} [{NOW.strftime('%Y-%m-%d')}]",
        "content": content_b64,
        "sha": sha or None,
        "branch": "main",
    }).encode()

    req = urllib.request.Request(
        API, data=data,
        headers={
            "Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
        method="PUT",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            raw_url = f"https://raw.githubusercontent.com/{REPO}/main/{repo_path}"
            print(f"✅ Uploaded: {raw_url}")
            return raw_url
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return ""


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

    # Step 2.5: Generate and upload image
    image_url = ""
    if HAS_IMAGE and total > 0:
        try:
            print("🖼️  Step 2.5: Generating image...")
            img_path = "/tmp/daily-brief.png"
            date_str = f"{DATE_LABEL} {WEEKDAY}"
            generate_image(all_news, img_path, date_str)
            print("📤 Uploading image to GitHub...")
            image_url = upload_to_github(img_path, "daily-brief.png")
            if image_url:
                print(f"   URL: {image_url}")
            print()
        except Exception as e:
            print(f"⚠️  Image generation skipped: {e}")
            print()

    # Step 3: Push
    print(f"📱 Step 3: Pushing to WeChat...")
    result = push_to_wechat(title, body, image_url)

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
