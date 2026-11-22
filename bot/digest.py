import html
import io
import json
import os
import random
import re
import subprocess

import feedparser
import requests
from bs4 import BeautifulSoup
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
            timeout=20,
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
            timeout=20,
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


def get_article_text_jina(url):
    jina_url = "https://r.jina.ai/" + url

    try:
        response = requests.get(
            jina_url,
            timeout=35,
            headers=HEADERS,
        )

        if not response.ok:
            print(
                f"Jina Reader вернул статус {response.status_code}: {url}"
            )
            return ""

        text = response.text

        if "Markdown Content:" in text:
            text = text.split(
                "Markdown Content:",
                1,
            )[1]

        text = clean_text(text)

        if len(text) > 400:
            print(f"Текст статьи получен через Jina Reader: {url}")
            return text

        print(f"Jina Reader вернул слишком мало текста: {url}")

    except Exception as error:
        print(f"Jina Reader: ошибка — {error}")

    return ""


def get_article_text_direct(url):
    try:
        response = requests.get(
            url,
            timeout=25,
            headers=HEADERS,
        )
        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "form",
                "button",
                "noscript",
            ]
        ):
            tag.decompose()

        article = (
            soup.find("article")
            or soup.find("main")
            or soup.find(
                "div",
                class_=re.compile(
                    r"(entry-content|article-content|post-content|content)",
                    re.IGNORECASE,
                ),
            )
        )

        if article:
            text = article.get_text(" ", strip=True)
        else:
            text = soup.get_text(" ", strip=True)

        text = clean_text(text)

        if len(text) > 400:
            print(f"Текст статьи получен напрямую: {url}")
            return text

        print(f"Прямое чтение дало слишком мало текста: {url}")

    except Exception as error:
        print(f"Прямое чтение статьи: ошибка — {error}")

    return ""


def get_article_text(url):
    article_text = get_article_text_jina(url)

    if article_text:
        return article_text

    return get_article_text_direct(url)


def get_best_sentence(article_text):
    if not article_text:
        return ""

    sentences = re.split(
        r"(?<=[.!?])\s+",
        article_text,
    )

    good_sentences = []

    for index, sentence in enumerate(sentences):
        sentence = sentence.strip()

        if len(sentence) < 90:
            continue

        if len(sentence) > 320:
            continue

        if sentence.count(" ") < 12:
            continue

        blocked_words = [
            "cookie",
            "cookies",
            "subscribe",
            "newsletter",
            "comment",
            "comments",
            "discord",
            "affiliate",
            "privacy",
            "advertisement",
            "sign up",
            "follow us",
            "share this",
            "read more",
            "related posts",
            "leave a reply",
            "copyright",
        ]

        if any(
            word in sentence.lower()
            for word in blocked_words
        ):
            continue

        good_sentences.append(
            (
                index,
                sentence,
            )
        )

    if not good_sentences:
        return ""

    strong_words = [
        "will offer",
        "offers",
        "offering",
        "features",
        "featuring",
        "introduces",
        "introducing",
        "announced",
        "announcing",
        "revealed",
        "revealing",
        "showcases",
        "showcasing",
        "launch",
        "launching",
        "release",
        "releasing",
        "available",
        "adds",
        "adding",
        "supports",
        "supporting",
        "optimized",
        "designed",
        "improved",
        "improving",
        "brings",
        "bringing",
        "includes",
        "including",
        "allows",
        "enables",
        "provides",
        "providing",
        "deliver",
        "delivering",
    ]

    scored_sentences = []

    for index, sentence in good_sentences:
        lower_sentence = sentence.lower()
        score = 0

        for word in strong_words:
            if word in lower_sentence:
                score += 3

        if re.search(
            r"\d",
            sentence,
        ):
            score += 1

        if 120 <= len(sentence) <= 260:
            score += 3

        if index < 12:
            score += 2

        scored_sentences.append(
            (
                score,
                index,
                sentence,
            )
        )

    scored_sentences.sort(
        key=lambda item: (
            item[0],
            -item[1],
        ),
        reverse=True,
    )

    return scored_sentences[0][2]


def get_hook(item):
    article_text = get_article_text(item["link"])

    best_sentence = get_best_sentence(article_text)

    if best_sentence:
        print("Выбрана сильная фраза из статьи:")
        print(best_sentence)

        russian_hook = translate_text(best_sentence)

        if russian_hook:
            return russian_hook

    summary = item.get("summary", "")

    if summary:
        best_sentence = get_best_sentence(summary)

        if best_sentence:
            print("Использую сильную фразу из RSS-описания.")
            return translate_text(best_sentence)

    print("Подходящая фраза не найдена.")
    return ""


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
    intro = get_intro()

    lines = [
        f"<b>{intro}</b>",
        "",
    ]

    for item in items:
        russian_title = translate_text(item["title"])
        safe_title = html.escape(russian_title)
        safe_link = html.escape(item["link"], quote=True)
        hook = get_hook(item)

        if hook:
            lines.append(
                f'• <b><a href="{safe_link}">{safe_title}</a></b>\n{hook}'
            )

        else:
            lines.append(
                f'• <b><a href="{safe_link}">{safe_title}</a></b>'
            )

        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def get_intro():
    intros = [
        "Подборка свежих новостей",
        "Новая подборка ретро-новостей",
        "А вот и подборка новейших ретро-новостей",
        "Свежие новости из мира ретро-гейминга",
        "Главные ретро-новости этой подборки",
        "Что нового в мире ретро-игр",
        "Свежая порция ретро-новостей",
        "Новости ретро-гейминга",
        "Самое интересное из мира ретро",
        "Новые события в ретро-гейминге",
        "Подборка актуальных ретро-новостей",
        "Ретро-новости, которые стоит увидеть",
    ]

    return random.choice(intros)


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
