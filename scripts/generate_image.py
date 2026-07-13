#!/usr/bin/env python3
"""
Generate a beautiful morning brief image for WeChat push.
Compatible with GitHub Actions (Ubuntu with Noto CJK fonts).
"""
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timezone, timedelta
import os

BJ_TZ = timezone(timedelta(hours=8))

# Color scheme
BG = (246, 247, 249)
WHITE = (255, 255, 255)
DARK = (26, 26, 46)
GRAY = (107, 114, 128)
BLUE = (67, 97, 238)
PURPLE = (114, 9, 183)
ORANGE = (247, 127, 0)
GREEN = (6, 167, 125)

CATEGORY_COLORS = {
    "ai": BLUE, "robot": ORANGE, "finance": GREEN,
}
CATEGORY_LABELS = {
    "ai": "AI领袖", "robot": "机器人", "finance": "泛金融",
}
CATEGORY_EMOJI = {
    "ai": "🧠", "robot": "🤖", "finance": "💰",
}

# Font paths for different OS
def _find_font(bold: bool = False):
    """Find a Chinese-capable font."""
    paths = []
    if bold:
        paths = [
            "/System/Library/Fonts/PingFang.ttc",          # macOS
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # Ubuntu
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        ]
    else:
        paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]

    for p in paths:
        if os.path.exists(p):
            return p
    return None


def get_font(size: int, bold: bool = False):
    font_path = _find_font(bold)
    try:
        if font_path:
            if "PingFang.ttc" in font_path:
                return ImageFont.truetype(font_path, size, index=1 if bold else 0)
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def draw_gradient_header(draw, W, date_str):
    header_h = 130
    for y in range(header_h):
        r = int(26 + (67 - 26) * y / header_h * 1.3)
        g = int(26 + (97 - 26) * y / header_h * 0.7)
        b = int(46 + (183 - 46) * y / header_h * 1.1)
        r, g, b = min(r, 67), min(g, 97), min(b, 183)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    font_date = get_font(22)
    draw.text((32, 20), date_str, fill=(180, 190, 220), font=font_date)
    font_title = get_font(48, bold=True)
    draw.text((32, 52), "🤖 Eric的每日AI早报", fill=WHITE, font=font_title)
    return header_h


def draw_news_card(draw, x, y, w, title, summary, color, num):
    padding = 18
    card_x = x + padding
    card_w = w - 2 * padding
    font_title = get_font(22, bold=True)
    font_summary = get_font(19)

    # Title
    title_text = f"{num}. {title}"
    title_bbox = font_title.getbbox(title_text)
    title_w = title_bbox[2] - title_bbox[0]

    # Truncate if too long
    if title_w > card_w:
        while title_w > card_w and len(title_text) > 5:
            title_text = title_text[:-1]
            title_w = font_title.getbbox(title_text + "...")[2] - font_title.getbbox(title_text + "...")[0]
        title_text += "..."

    # Summary (max 2 lines, ~25 chars each)
    if summary:
        summary = summary[:50].strip()
    else:
        summary = "暂无摘要"

    # Card height
    title_h = 30
    desc_h = 24
    card_h = padding + title_h + 8 + desc_h + padding

    # Draw card
    draw.rounded_rectangle([x, y, x + w, y + card_h], radius=12, fill=WHITE)
    draw.rectangle([x, y + 8, x + 4, y + card_h - 8], fill=color)

    # Draw text
    draw.text((card_x, y + padding - 2), title_text, fill=DARK, font=font_title)
    draw.text((card_x, y + padding + title_h + 8), summary, fill=GRAY, font=font_summary)

    return card_h + 10


def generate_image(all_news, output_path, date_label=""):
    W = 760
    padding = 28
    card_w = W - 2 * padding
    header_h = 130
    y = header_h + padding

    # Calculate height
    for items in all_news.values():
        if not items:
            continue
        y += 44 + 12  # category header
        for _ in items:
            y += 88  # approximate card height
    y += padding
    total_h = y

    img = Image.new("RGB", (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    header_h = draw_gradient_header(draw, W, date_label)
    y = header_h + padding

    global_num = 1
    for category in ["ai", "robot", "finance"]:
        items = all_news.get(category, [])
        if not items:
            continue

        color = CATEGORY_COLORS[category]
        emoji = CATEGORY_EMOJI[category]
        label = CATEGORY_LABELS[category]

        font_cat = get_font(26, bold=True)
        draw.text((padding + 2, y), f"{emoji} {label}  ({len(items)}条)", fill=color, font=font_cat)
        y += 44

        for item in items:
            title = item.get("title", "")
            summary = item.get("description", "") or ""
            h = draw_news_card(draw, padding, y, card_w, title, summary, color, global_num)
            y += h
            global_num += 1

        y += 16

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    size = os.path.getsize(output_path)
    print(f"✅ Image: {output_path} ({size} bytes, {W}x{total_h})")
    return output_path
