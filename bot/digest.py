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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return set(json.load(file))
    except Exception as error:
        print(f"Не удалось прочитать sent_links.json: {error}")
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
                print(f"Использую сохранённый chat_id: {chat_id}")
                return chat_id

    response = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        timeout=20,
    )
    response.raise_for_status()

    updates = response.json().get("result", [])

    for update in reversed(updates):
        message = update.get("message") or update.get("channel_post")

        if message:
            chat_id = str(message["chat"]["id"])

            with open(CHAT_ID_FILE, "w", encoding="utf-8") as file:
                file.write(chat_id)

            print(f"Найден chat_id: {chat_id}")
            return chat_id

    raise RuntimeError(
        "Не удалось определить chat_id. "
        "Открой бота в Telegram, отправь /start и запусти workflow снова."
    )


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
            timeout=15,
            headers=HEADERS,
        )
        response.raise_for_status()
        data = response.json()

        translated = data.get(
            "responseData",
            {},
        ).get(
            "translatedText",
            "",
        )
        translated = html.unescape(translated).strip()

        if translated and translated != text:
            print(f"Перевод (MyMemory): {translated}")
            return translated

    except Exception as error:
        print(f"Перевод (MyMemory): ошибка — {error}")

    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "ru",
                "dt": "t",
                "q": text,
            },
            timeout=15,
            headers=HEADERS,
        )
        response.raise_for_status()
        data = response.json()

        translated = "".join(
            part[0]
            for part in data[0]
            if part and part[0]
        ).strip()

        if translated and translated != text:
            print(f"Перевод (Google): {translated}")
            return translated

    except Exception as error:
        print(f"Перевод (Google): ошибка — {error}")

    print(f"Перевод не выполнен: {text}")
    return text


def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_entry_summary(entry):
    text = ""

    if entry.get("content"):
        for content in entry.get("content", []):
            text += content.get("value", "") + " "

    if not text and entry.get("summary"):
        text = entry.get("summary", "")

    if not text and entry.get("description"):
        text = entry.get("description", "")

    return clean_text(text)


def get_entry_image(entry):
    for media in entry.get("media_content", []):
        url = media.get("url", "")

        if url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return url

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
    text = title + " " + summary

    hooks = [
        (
            ["nintendo ds", "nds", "dualstation"],
            "Старая Nintendo DS получает новую жизнь.",
        ),
        (
            ["game boy", "gameboy"],
            "Классика Game Boy всё ещё способна удивлять.",
        ),
        (
            ["game boy color", "gbc"],
            "Игры для Game Boy Color снова находят новое применение.",
        ),
        (
            ["steam deck"],
            "Steam Deck расширяет возможности портативного гейминга.",
        ),
        (
            [
                "ayn thor",
                "retroid pocket",
                "anbernic",
                "miyoo",
                "trimui",
            ],
            "Портативные консоли продолжают становиться интереснее.",
        ),
        (
            ["handheld", "portable"],
            "Портативный ретро-гейминг снова в центре внимания.",
        ),
        (
            ["nintendo"],
            "В мире Nintendo снова происходит интересное.",
        ),
        (
            ["playstation", "ps1", "ps2", "sony"],
            "Классика PlayStation продолжает жить в фанатских проектах.",
        ),
        (
            ["sega", "genesis", "mega drive", "dreamcast"],
            "Sega не перестаёт радовать поклонников классики.",
        ),
        (
            ["emulator", "emulation"],
            "Эмуляторы продолжают менять ретро-гейминг.",
        ),
        (
            ["mod", "mods", "modding"],
            "Моддинг открывает старым играм и устройствам новую жизнь.",
        ),
        (
            ["hack", "custom firmware", "cfw"],
            "Кастомные прошивки делают ретро-железо гибче.",
        ),
        (
            ["fan-made", "fan made", "fan project"],
            "Фанаты создают новые проекты по мотивам классики.",
        ),
        (
            ["restoration", "restored", "repair"],
            "Реставрация возвращает старой технике вторую жизнь.",
        ),
        (
            ["kickstarter", "crowdfunding"],
            "Новый ретро-проект ищет поддержку у сообщества.",
        ),
        (
            ["review"],
            "Разбираемся, стоит ли это внимания.",
        ),
        (
            ["guide", "tutorial", "how to"],
            "Полезный материал для ретро-геймера.",
        ),
        (
            ["update"],
            "Свежее обновление, которое может быть важным.",
        ),
        (
            ["release", "launched"],
            "Свежий релиз, на который стоит взглянуть.",
        ),
        (
            ["sale", "discount", "deal"],
            "Хороший повод пополнить ретро-коллекцию.",
        ),
        (
            ["hardware", "device"],
            "Железо для ретро-гейминга не стоит на месте.",
        ),
        (
            ["controller", "gamepad"],
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

    for keywords, hook in hooks:
        for keyword in keywords:
            if keyword in title:
                return hook

    for keywords, hook in hooks:
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
        print(f"Читаю RSS: {source_name}")

        try:
            response = requests.get(
                feed_url,
                timeout=20,
                headers=HEADERS,
            )
            response.raise_for_status()

            feed = feedparser.parse(response.content)

        except Exception as error:
            print(
                f"Не удалось прочитать RSS {source_name}: {error}"
            )
            continue

        print(
            f"RSS {source_name}: найдено {len(feed.entries)} записей."
        )

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            title = html.unescape(
                entry.get("title", "")
            ).strip()

            if not link or not title:
                continue

            if link in sent_links:
                continue

            items.append(
                {
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "summary": get_entry_summary(entry),
                    "image_url": get_entry_image(entry),
                    "published": entry.get("published_parsed"),
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
        response = requests.get(
            url,
            timeout=15,
            headers=HEADERS,
        )
        response.raise_for_status()

        image = Image.open(
            io.BytesIO(response.content)
        ).convert("RGB")

        return image

    except Exception as error:
        print(
            f"Не удалось скачать изображение: {error}"
        )
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
        font=title_font,
        fill="white",
    )

    draw.text(
        (80, 240),
        "Retro Handhelds + Retro Dodo",
        font=subtitle_font,
        fill=(190, 190, 200),
    )

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

        positions = [
            (80, 360),
            (620, 360),
            (80, 790),
            (620, 790),
        ]

        for index, (item, image) in enumerate(images):
            x, y = positions[index]

            card = crop_to_ratio(
                image,
                card_width,
                card_height,
            )

            canvas.paste(card, (x, y))

            draw.rectangle(
                [
                    x,
                    y,
                    x + card_width,
                    y + card_height,
                ],
                outline=accent,
                width=4,
            )

            draw.text(
                (x + 16, y + card_height - 48),
                item["source"],
                font=label_font,
                fill="white",
            )

    draw.text(
        (80, 1330),
        "только свежие новости из мира ретро",
        font=footer_font,
        fill="white",
    )

    canvas.save(COLLAGE_FILE, "PNG")
    print("Коллаж создан.")


def send_digest(chat_id, items, message):
    build_collage(items)

    caption = message

    while len(caption) > 1024 and len(items) > 1:
        items.pop()
        caption = build_message(items)

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
    print("Дайджест отправлен в Telegram.")


def main():
    sent_links = load_state()
    items = collect_new_items(sent_links)

    if not items:
        print("Новых публикаций нет. Сообщение не отправляется.")
        return

    print(f"Найдено новых новостей: {len(items)}")

    chat_id = get_chat_id()
    message = build_message(items)

    send_digest(
        chat_id,
        items,
        message,
    )

    sent_links.update(item["link"] for item in items)
    save_state(sent_links)
    commit_state()

    print("Работа завершена успешно.")


if __name__ == "__main__":
    main()
