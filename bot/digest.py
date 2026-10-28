import base64
import html
import io
import json
import os
import re
import subprocess
import urllib.parse

import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont

FEEDS = [
    ("Retro Handhelds", "https://retrohandhelds.gg/feed/"),
    ("Retro Dodo", "https://retrododo.com/rss/"),
]

STATE_FILE = "bot/sent_links.json"
COLLAGE_FILE = "bot/collage.png"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GIT_EMAIL = "actions@github.com"
GIT_NAME = "GitHub Actions"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return set(json.load(file))
    return set()


def save_state(sent_links):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(sent_links), file, ensure_ascii=False, indent=2)


def commit_state():
    subprocess.run(["git", "config", "user.name", GIT_NAME], check=True)
    subprocess.run(["git", "config", "user.email", GIT_EMAIL], check=True)
    subprocess.run(["git", "add", STATE_FILE], check=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
    )

    if result.returncode == 0:
        return

    subprocess.run(
        ["git", "commit", "-m", "Update sent links"],
        check=True,
    )
    subprocess.run(["git", "push"], check=True)


def get_chat_id():
    response = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        timeout=30,
    )
    response.raise_for_status()
    updates = response.json().get("result", [])

    for update in reversed(updates):
        message = update.get("message") or update.get("channel_post")
        if message:
            return message["chat"]["id"]

    raise RuntimeError("Не удалось определить chat_id.")


def translate_text(text):
    if not text:
        return text

    try:
        response = requests.get(
            "https://api.mymemory.translated.net/get",
            params={
                "q": text,
                "langpair": "en|ru",
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        translated = data.get("responseData", {}).get("translatedText", "")
        translated = html.unescape(translated).strip()

        if translated and translated.upper() != "MYMEMORY WARNING":
            return translated
    except Exception as error:
        print(f"Перевод MyMemory не сработал: {error}")

    print(f"Перевод не выполнен, отправляю оригинал: {text}")
    return text


def collect_new_items(sent_links):
    new_items = []

    for source_name, feed_url in FEEDS:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            title = html.unescape(entry.get("title", "")).strip()

            if not link or not title or link in sent_links:
                continue

            image_url = None

            for media in entry.get("media_content", []):
                if media.get("url", "").lower().endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                ):
                    image_url = media["url"]
                    break

            if not image_url:
                for media in entry.get("media_thumbnail", []):
                    image_url = media.get("url")
                    break

            if not image_url:
                for enclosure in entry.get("links", []):
                    if enclosure.get("rel") == "enclosure" and enclosure.get(
                        "type", ""
                    ).startswith("image/"):
                        image_url = enclosure.get("href")
                        break

            new_items.append(
                {
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "image_url": image_url,
                }
            )

    return new_items


def build_message(items):
    lines = ["<b>Retro Game Grave</b>", ""]

    for item in items:
        russian_title = translate_text(item["title"])
        safe_title = html.escape(russian_title)
        safe_link = html.escape(item["link"], quote=True)
        source = html.escape(item["source"])

        lines.append(
            f'• <a href="{safe_link}">{safe_title}</a>\n{source}'
        )
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def download_image(url):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        return image
    except Exception:
        return None


def crop_to_ratio(image, width, height):
    target_ratio = width / height
    image_ratio = image.width / image.height

    if image_ratio > target_ratio:
        new_width = int(image.height * target_ratio)
        left = (image.width - new_width) // 2
        image = image.crop((left, 0, left + new_width, image.height))
    else:
        new_height = int(image.width / target_ratio)
        top = (image.height - new_height) // 2
        image = image.crop((0, top, image.width, top + new_height))

    return image.resize((width, height))


def load_font(size):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_collage(items):
    width, height = 1200, 1500
    background = (18, 18, 22)
    accent = (150, 90, 255)
    cyan = (60, 210, 220)

    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(84)
    subtitle_font = load_font(38)
    label_font = load_font(28)
    footer_font = load_font(34)

    draw.text((80, 70), "Retro Game Grave", font=title_font, fill="white")
    draw.text((80, 185), "Каждое утро в 8:00", font=subtitle_font, fill=cyan)
    draw.text((80, 240), "Retro Handhelds + Retro Dodo", font=subtitle_font, fill=(190, 190, 200))

    images = []

    for item in items:
        if item.get("image_url"):
            image = download_image(item["image_url"])
            if image:
                images.append((item, image))

        if len(images) == 4:
            break

    if not images:
        draw.text(
            (80, 650),
            "Сегодня нет изображений\nдля коллажа",
            font=subtitle_font,
            fill="white",
        )
    else:
        card_width = 500
        card_height = 380
        positions = [(80, 360), (620, 360), (80, 790), (620, 790)]

        for index, (item, image) in enumerate(images):
            x, y = positions[index]
            card = crop_to_ratio(image, card_width, card_height)
            canvas.paste(card, (x, y))
            draw.rectangle(
                [x, y, x + card_width, y + card_height],
                outline=accent,
                width=4,
            )
            label = item["source"]
            draw.text((x + 16, y + card_height - 48), label, font=label_font, fill="white")

    draw.text(
        (80, 1330),
        "только свежие новости из мира ретро",
        font=footer_font,
        fill="white",
    )

    canvas.save(COLLAGE_FILE, "PNG")


def send_digest(chat_id, message):
    build_collage(current_items)

    caption = message

    while len(caption) > 1024 and len(current_items) > 1:
        current_items.pop()
        caption = build_message(current_items)

    if len(caption) > 1024:
        caption = caption[:1021].rstrip() + "..."

    with open(COLLAGE_FILE, "rb") as photo:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
            },
            files={"photo": photo},
            timeout=60,
        )

    response.raise_for_status()


def main():
    global current_items

    sent_links = load_state()
    current_items = collect_new_items(sent_links)

    if not current_items:
        print("Новых публикаций нет. Сообщение не отправляется.")
        return

    chat_id = get_chat_id()
    message = build_message(current_items)
    send_digest(chat_id, message)

    sent_links.update(item["link"] for item in current_items)
    save_state(sent_links)
    commit_state()


if __name__ == "__main__":
    main()
