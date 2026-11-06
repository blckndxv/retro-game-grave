import asyncio
import os

import edge_tts
from pydub import AudioSegment

VOICE = "ru-RU-DmitryNeural"
VOICE_FILE = "bot/audio/voice.mp3"
BACKGROUND_FILE = "bot/audio/background.mp3"
OUTPUT_FILE = "bot/audio/test_digest.mp3"

TEXT = (
    "Привет! Это тестовая аудиоверсия Retro Game Grave. "
    "Сегодня мы проверяем русский голос, паузы и фоновую музыку. "
    "Скоро здесь будут главные новости из мира ретро-игр и портативных консолей."
)


async def create_voice():
    communicate = edge_tts.Communicate(TEXT, VOICE)
    await communicate.save(VOICE_FILE)


def mix_audio():
    if not os.path.exists(BACKGROUND_FILE):
        print("Фоновая музыка не найдена. Создаю только голос.")
        os.rename(VOICE_FILE, OUTPUT_FILE)
        return

    voice = AudioSegment.from_file(VOICE_FILE, format="mp3")
    music = AudioSegment.from_file(BACKGROUND_FILE, format="mp3")

    music = music[: len(voice)]
    music = music - 24

    mixed = music.overlay(voice)
    mixed.export(OUTPUT_FILE, format="mp3", bitrate="128k")

    print(f"Готово: {OUTPUT_FILE}")


async def main():
    await create_voice()
    mix_audio()


if __name__ == "__main__":
    asyncio.run(main())
