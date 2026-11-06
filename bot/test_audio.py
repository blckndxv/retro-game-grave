import asyncio
import glob
import os
import random

import edge_tts
from gtts import gTTS
from pydub import AudioSegment

VOICE = "ru-RU-SvetlanaNeural"
VOICE_RATE = "+25%"
VOICE_FILE = "bot/audio/voice.mp3"
BACKGROUND_FOLDER = "bot/audio"
OUTPUT_FILE = "bot/audio/test_digest.mp3"

TEXT = (
    "Привет! Это тестовая аудиоверсия Retro Game Grave. "
    "Сегодня мы проверяем русский голос, скорость речи и фоновую музыку. "
    "Скоро здесь будут главные новости из мира ретро-игр и портативных консолей."
)


async def create_edge_voice():
    communicate = edge_tts.Communicate(
        TEXT,
        VOICE,
        rate=VOICE_RATE,
        volume="+0%",
        pitch="+0Hz",
    )
    await communicate.save(VOICE_FILE)


def create_gtts_voice():
    speech = gTTS(text=TEXT, lang="ru")
    speech.save(VOICE_FILE)


async def create_voice():
    try:
        await create_edge_voice()
        print("Голос создан через Edge TTS.")
        return
    except Exception as error:
        print(f"Edge TTS не сработал: {error}")

    print("Создаю голос через gTTS.")
    create_gtts_voice()


def choose_background():
    files = glob.glob(os.path.join(BACKGROUND_FOLDER, "*.mp3"))
    files = [
        file
        for file in files
        if os.path.basename(file) not in ("voice.mp3", "test_digest.mp3")
    ]

    if not files:
        return None

    return random.choice(files)


def mix_audio():
    background_file = choose_background()

    if not background_file:
        print("Фоновая музыка не найдена. Создаю только голос.")
        os.replace(VOICE_FILE, OUTPUT_FILE)
        return

    print(f"Выбран фон: {background_file}")

    voice = AudioSegment.from_file(VOICE_FILE, format="mp3")
    music = AudioSegment.from_file(background_file, format="mp3")

    if len(music) < len(voice):
        repeats = (len(voice) // len(music)) + 1
        music = music * repeats

    music = music[: len(voice)]
    music = music - 12

    mixed = music.overlay(voice)
    mixed.export(OUTPUT_FILE, format="mp3", bitrate="128k")

    print(f"Готово: {OUTPUT_FILE}")


async def main():
    await create_voice()
    mix_audio()


if __name__ == "__main__":
    asyncio.run(main())
