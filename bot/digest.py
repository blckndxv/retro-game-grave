import html
import io
import json
import os
import random
import re
import subprocess

import feedparser
import requests
from PIL import Image, ImageDraw, ImageFont

FEEDS = [
    ("Retro Handhelds", "https://retrohandhelds.gg/feed/"),
    ("Retro Dodo", "https://retrododo.com/rss/"),
]

STATE_FILE = "bot/sent_links.json"
CHAT_ID_FILE = "bot/chat_id.txt"
COLLAGE_FILE = "bot/collage.png"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GIT_EMAIL = "actions@github.com"
GIT_NAME = "GitHub Actions"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                return set(data)
        except Exception:
            return set()

    return set()


def save_state(sent_links):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            sorted(sent_links),
            file,
            ensure_ascii=False,
            indent=2,
        )


def commit_state():
    subprocess.run(
        ["git", "config", "user.name", GIT_NAME],
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", GIT_EMAIL],
        check=True,
    )

    subprocess.run(
        ["git", "add", "bot/sent_links.json"],
        check=True,
    )

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
    )

    if result.returncode == 0:
        print("Изменений для сохранения нет.")
        return

    subprocess.run(
        ["git", "commit", "-m", "Update sent links"],
        check=True,
    )
    subprocess.run(["git", "push"], check=True)


def get_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r", encoding="utf-8") as file:
            chat_id = file.read().strip()

            if chat_id:
                return chat_id

    response = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        timeout=30,
    )
    response.raise_for_status()

    updates = response.json().get("result", [])

    for update in reversed(updates):
        message = update.get("message") or update.get("channel_post")

        if message:
            chat_id = str(message["chat"]["id"])

            with open(CHAT_ID_FILE, "w", encoding="utf-8") as file:
                file.write(chat_id)

            return chat_id

    raise RuntimeError(
        "Не удалось определить chat_id. "
        "Открой бота в Telegram, отправь /start и запусти workflow снова."
    )


def translate_text(text):
    if not text:
        return text

    providers = [
        (
            "Google Chrome",
            "https://clients5.google.com/translate_a/t",
            {
                "client": "dict-chrome-ex",
                "sl": "auto",
                "tl": "ru",
                "q": text,
            },
        ),
        (
            "Google Classic",
            "https://translate.googleapis.com/translate_a/single",
            {
                "client": "gtx",
                "sl": "auto",
                "tl": "ru",
                "dt": "t",
                "q": text,
            },
        ),
        (
            "MyMemory",
            "https://api.mymemory.translated.net/get",
            {
                "q": text,
                "langpair": "en|ru",
            },
        ),
    ]

    for provider_name, url, params in providers:
        try:
            response = requests.get(
                url,
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

            translated = ""

            if provider_name == "MyMemory":
                translated = data.get(
                    "responseData",
                    {},
                ).get(
                    "translatedText",
                    "",
                )
                translated = html.unescape(translated).strip()

            else:
                translated = "".join(
                    part[0]
                    for part in data[0]
                    if part and part[0]
                ).strip()

            if translated and translated != text:
                print(
                    f"Перевод ({provider_name}): {translated}"
                )
                return translated

            print(
                f"{provider_name}: не смог перевести текст."
            )

        except Exception as error:
            print(
                f"{provider_name}: ошибка — {error}"
            )

    print(
        f"Перевод не выполнен, оставляю оригинал: {text}"
    )
    return text


def get_entry_text(entry):
    text = ""

    if entry.get("content"):
        for content in entry.get("content", []):
            text += content.get("value", "") + " "

    if not text and entry.get("summary"):
        text = entry.get("summary", "")

    if not text and entry.get("description"):
        text = entry.get("description", "")

    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_entry_image(entry):
    for media in entry.get("media_content", []):
        if media.get("url", "").lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return media["url"]

    for media in entry.get("media_thumbnail", []):
        if media.get("url"):
            return media["url"]

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure":
            if link.get("type", "").startswith("image/"):
                return link.get("href")

    return None


def get_hook(item):
    title = item["title"].lower()
    summary = item["summary"].lower()

    specific_hooks = [
        (
            ["game boy", "gameboy"],
            "Классика Game Boy всё ещё жива.",
        ),
        (
            ["steam deck"],
            "Steam Deck расширяет возможности портативного гейминга.",
        ),
        (
            ["nintendo"],
            "В мире Nintendo снова происходит интересное.",
        ),
        (
            ["sony", "playstation"],
            "Sony и ретро-игры — история продолжается.",
        ),
        (
            ["sega", "genesis", "mega drive"],
            "Sega не перестаёт радовать поклонников классики.",
        ),
        (
            ["emulator", "emulation"],
            "Эмуляторы продолжают менять ретро-гейминг.",
        ),
        (
            ["handheld", "handhelds", "portable"],
            "Портативный ретро-гейминг снова в центре внимания.",
        ),
        (
            ["console", "consoles"],
            "Ещё одна страница истории консолей.",
        ),
        (
            ["mod", "mods", "modding"],
            "Моддинг открывает старым устройствам новую жизнь.",
        ),
        (
            ["hack", "custom firmware", "cfw"],
            "Кастомные прошивки делают ретро-железо гибче.",
        ),
        (
            ["restoration", "restore", "restored"],
            "Реставрация возвращает классике вторую жизнь.",
        ),
        (
            ["collection", "collector", "collecting"],
            "Коллекционирование ретро-игр — отдельное искусство.",
        ),
        (
            ["review", "reviewed"],
            "Разбираемся, стоит ли это внимания.",
        ),
        (
            ["guide", "how to", "tutorial"],
            "Полезный материал для ретро-геймера.",
        ),
        (
            ["update", "updated"],
            "Свежее обновление, которое может быть важным.",
        ),
        (
            ["release", "released", "launched"],
            "Свежий релиз, на который стоит взглянуть.",
        ),
        (
            ["sale", "discount", "deal"],
            "Хороший повод пополнить ретро-коллекцию.",
        ),
        (
            ["hardware", "device", "console mod"],
            "Железо для ретро-гейминга не стоит на месте.",
        ),
        (
            ["controller", "gamepad", "joystick"],
            "Геймпады и управление — важная часть ностальгии.",
        ),
        (
            ["android"],
            "Android-гейминг становится всё интереснее.",
        ),
        (
            ["linux"],
            "Linux снова доказывает свою силу в играх.",
        ),
    ]

    for keywords, hook in specific_hooks:
        for keyword in keywords:
            if keyword in title:
                return hook

    for keywords, hook in specific_hooks:
        for keyword in keywords:
            if keyword in summary:
                return hook

    neutral_hooks = [
        "Свежая новость из мира ретро-гейминга.",
        "Интересное событие для поклонников классики.",
        "Ещё одна новость из мира старых игр и консолей.",
        "Ретро-гейминг продолжает удивлять.",
        "Новая история из мира игровых классиков.",
    ]

    return random.choice(neutral_hooks)


def collect_new_items(sent_links):
    items = []

    for source_name, feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as error:
            print(f"Не удалось прочитать RSS {source_name}: {error}")
            continue

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            title = html.unescape(entry.get("title", "")).strip()

            if not link or not title or link in sent_links:
                continue

            published = entry.get("published_parsed")
            summary = get_entry_text(entry)
            image_url = get_entry_image(entry)

            items.append(
                {
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "image_url": image_url,
                    "published": published,
                }
            )

    items.sort(
        key=lambda item: item["published"]
        or (0, 0, 0, 0, 0, 0, 0, 0, 0),
        reverse=True,
    )

    return items[:10]


def build_message(items):
    lines = [
        "<b>Retro Game Grave</b>",
        "",
    ]

    for item in items:
        russian_title = translate_text(item["title"])
        safe_title = html.escape(russian_title)
        safe_link = html.escape(item["link"], quote=True)
        hook = get_hook(item)

        lines.append(
            f'• <b><a href="{safe_link}">{safe_title}</a></b>\n{hook}'
        )
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def download_image(url):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()

        image = Image.open(
            io.BytesIO(response.content)
        ).convert("RGB")

        return image

    except Exception as error:
        print(f"Не удалось скачать изображение: {error}")
        return None


def crop_to_ratio(image, width, height):
    target_ratio = width / height
    image_ratio = image.width / image.height

    if image_ratio > target_ratio:
        new_width = int(image.height * target_ratio)
        left = (image.width - new_width) // 2

        image = image.crop(
            (
                left,
                0,
                left + new_width,
                image.height,
            )
        )

    else:
        new_height = int(image.width / target_ratio)
        top = (image.height - new_height) // 2

        image = image.crop(
            (
                0,
                top,
                image.width,
                top + new_height,
            )
        )

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

    canvas = Image.new(
        "RGB",
        (width, height),
        background,
    )
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(84)
    subtitle_font = load_font(38)
    label_font = load_font(28)
    footer_font = load_font(34)

    draw.text(
        (80, 70),
        "Retro Game Grave",
        font=title_
