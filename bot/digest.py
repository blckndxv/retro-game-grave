import glob
import html
import io
import json
import os
import random
import re
import subprocess

import feedparser
import requests
import trafilatura
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from pydub import AudioSegment

FEEDS = [
    ("Retro Handhelds", "https://retrohandhelds.gg/feed/"),
    ("Retro Dodo", "https://retrododo.com/rss/"),
]

STATE_FILE = "bot/sent_links.json"
CHAT_ID_FILE = "bot/chat_id.txt"
COLLAGE_FILE = "bot/collage.png"

AUDIO_FOLDER = "bot/audio"
RAW_VOICE_FILE = "/tmp/voice_raw.mp3"
FAST_VOICE_FILE = "/tmp/voice_fast.mp3"
AUDIO_FILE = "/tmp/digest.mp3"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GIT_EMAIL = "actions@github.com"
GIT_NAME = "GitHub Actions"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return set(json.load(file))
    return set()


def save_state(sent_links):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(sent_links), file, ensure_ascii=False, indent=2)


def commit_state():
    subprocess.run(["git", "config", "user.name", GIT_NAME], check=True)
    subprocess.run(["git", "config", "user.email", GIT_EMAIL], check=True)

    subprocess.run(["git", "add", "bot/sent_links.json"], check=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
    )

    if result.returncode == 0:
        print("Изменений для сохранения нет.")
        return

    subprocess.run(
        ["git", "commit", "-m", "Update digest state"],
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
        "Открой @RetroGameGraveNewsBot в Telegram, отправь /start "
        "и запусти workflow ещё раз."
    )


def translate_text(text):
    if not text:
        return text

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
        )
        response.raise_for_status()
        data = response.json()
        translated = "".join(
            part[0]
            for part in data[0]
            if part and part[0]
        ).strip()

        if translated and translated != text:
            print(f"Google Translate: OK — {translated}")
            return translated

        print(f"Google Translate: не перевёл — {text}")
    except Exception as error:
        print(f"Google Translate: ошибка — {error}")

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

        if translated and translated != text:
            print(f"MyMemory: OK — {translated}")
            return translated

        print(f"MyMemory: не перевёл — {text}")
    except Exception as error:
        print(f"MyMemory: ошибка — {error}")

    print(f"Перевод не выполнен, отправляю оригинал: {text}")
    return text


def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_entry_text(entry):
    text = ""

    if entry.get("content"):
        for content in entry.get("content", []):
            text += content.get("value", "") + " "

    if not text and entry.get("summary"):
        text = entry.get("summary", "")

    if not text and entry.get("description"):
        text = entry.get("description", "")

    return clean_text(text)


def fetch_article_text(url):
    try:
        downloaded = trafilatura.fetch_url(url)

        if not downloaded:
            print(f"Страница не скачалась: {url}")
            return ""

        article = trafilatura.extract(
            downloaded,
            url=url,
            favor_recall=True,
            include_comments=False,
            include_tables=False,
        )

        if not article:
            print(f"Текст статьи не извлёкся: {url}")
            return ""

        return clean_text(article)
    except Exception as error:
        print(f"Не удалось извлечь текст статьи {url}: {error}")
        return ""


def translate_chunk(text):
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={
            "client": "gtx",
            "sl": "auto",
            "tl": "ru",
            "dt": "t",
            "q": text,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    return "".join(
        part[0]
        for part in data[0]
        if part and part[0]
    ).strip()


def translate_long_text(text):
    if not text:
        return ""

    chunks = []

    while text:
        chunks.append(text[:4000])
        text = text[4000:]

    translated_parts = []

    for index, chunk in enumerate(chunks, start=1):
        try:
            translated = translate_chunk(chunk)

            if translated:
                translated_parts.append(translated)
                print(f"Перевод части {index}: OK")
        except Exception as error:
            print(f"Перевод части {index}: ошибка — {error}")

    return " ".join(translated_parts).strip()


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

            published = entry.get("published_parsed")
            feed_text = get_entry_text(entry)

            new_items.append(
                {
                    "source": source_name,
                    "title": title,
                    "link": link,
                    "image_url": image_url,
                    "published": published,
                    "feed_text": feed_text,
                }
            )

    new_items.sort(
        key=lambda item: item["published"] or (0, 0, 0, 0, 0, 0, 0, 0, 0),
        reverse=True,
    )

    return new_items[:10]


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


def build_audio_text(items):
    lines = [
        "Привет! Это аудиоверсия Retro Game Grave.",
        "Сегодня в выпуске:",
    ]

    for index, item in enumerate(items[:3], start=1):
        title = translate_text(item["title"])
        article = fetch_article_text(item["link"])

        if not article:
            article = item.get("feed_text", "")

        if article:
            article = article[:2500].strip()
            article_ru = translate_long_text(article)
        else:
            article_ru = ""

        lines.append(f"Новость номер {index}: {title}.")

        if article_ru:
            lines.append(article_ru)
        else:
            lines.append(
                "Подробный текст этой новости пока не удалось получить. "
                "Ссылка на оригинал есть в текстовом дайджесте."
            )

    lines.append("Это были главные новости Retro Game Grave.")
    return " ".join(lines)


def create_audio(text):
    speech = gTTS(text=text, lang="ru")
    speech.save(RAW_VOICE_FILE)

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            RAW_VOICE_FILE,
            "-filter:a",
            "atempo=1.25",
            FAST_VOICE_FILE,
        ],
        check=True,
    )

    background_files = [
        file
        for file in glob.glob(os.path.join(AUDIO_FOLDER, "*.mp3"))
        if os.path.basename(file)
        not in ("voice_raw.mp3", "voice_fast.mp3", "digest.mp3")
    ]

    if not background_files:
        print("Фоновая музыка не найдена. Отправляю голос без фона.")
        os.replace(FAST_VOICE_FILE, AUDIO_FILE)
        return

    background_file = random.choice(background_files)
    print(f"Выбран фон: {background_file}")

    voice = AudioSegment.from_file(FAST_VOICE_FILE, format="mp3")
    music = AudioSegment.from_file(background_file, format="mp3")

    if len(music) < len(voice):
        repeats = (len(voice) // len(music)) + 1
        music = music * repeats

    music = music[: len(voice)]
    music = music - 6

    mixed = music.overlay(voice)
    mixed.export(AUDIO_FILE, format="mp3", bitrate="128k")

    print(f"Аудиоверсия готова: {AUDIO_FILE}")


def send_audio(chat_id):
    if not os.path.exists(AUDIO_FILE):
        print("Аудиофайл не создан. Пропускаю отправку аудио.")
        return

    with open(AUDIO_FILE, "rb") as audio:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendAudio",
            data={
                "chat_id": chat_id,
                "caption": "🎧 Аудиоверсия дайджеста",
                "title": "Retro Game Grave",
                "performer": "Retro Game Grave",
            },
            files={"audio": audio},
            timeout=120,
        )

    response.raise_for_status()
    print("Аудиоверсия отправлена в Telegram.")


def download_image(url):
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
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

    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(84)
    subtitle_font = load_font(38)
    label_font = load_font(28)
    footer_font = load_font(34)

    draw.text((80, 70), "Retro Game Grave", font=title_font, fill="white")
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
            card = crop_to_ratio(image, card_width, card_height)
            canvas.paste(card, (x, y))
            draw.rectangle(
                [x, y, x + card_width, y + card_height],
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

    audio_text = build_audio_text(current_items)
    create_audio(audio_text)
    send_audio(chat_id)


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
