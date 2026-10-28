import os
import html
import feedparser
import requests

FEEDS = [
    "https://retrohandhelds.gg/feed/",
    "https://retrododo.com/rss/",
]

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def get_chat_id():
    response = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
        timeout=30,
    )
    response.raise_for_status()
    updates = response.json().get("result", [])

    if not updates:
        raise RuntimeError(
            "Нет обновлений. Открой @RetroGameGraveNewsBot в Telegram, "
            "нажми Start, затем запусти workflow ещё раз."
        )

    for update in reversed(updates):
        message = update.get("message") or update.get("channel_post")
        if message:
            return message["chat"]["id"]

    raise RuntimeError("Не удалось определить chat_id.")


def build_digest():
    items = []

    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:
            title = html.unescape(entry.get("title", "")).strip()
            link = entry.get("link", "")
            if title and link:
                items.append(f"• {title}\n{link}")

    if not items:
        return "Retro Game Grave\n\nСегодня новых публикаций не найдено."

    return "Retro Game Grave\n\n" + "\n\n".join(items[:10])


def send_message(chat_id, text):
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    response.raise_for_status()


def main():
    chat_id = get_chat_id()
    send_message(chat_id, build_digest())


if __name__ == "__main__":
    main()
