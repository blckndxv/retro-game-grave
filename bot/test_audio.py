import glob
import os
import random
import subprocess

from gtts import gTTS
from pydub import AudioSegment

VOICE_FILE = "bot/audio/voice_raw.mp3"
VOICE_FILE_FAST = "bot/audio/voice.mp3"
BACKGROUND_FOLDER = "bot/audio"
OUTPUT_FILE = "bot/audio/test_digest.mp3"

TEXT = (
    "Привет! Это тестовая аудиоверсия Retro Game Grave. "
    "Сегодня мы проверяем русский голос, скорость речи и фоновую музыку. "
    "Скоро здесь будут главные новости из мира ретро-игр и портативных консолей."
)


def create_voice():
    speech = gTTS(text=TEXT, lang="ru")
    speech.save(VOICE_FILE)


def make_voice_faster():
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            VOICE_FILE,
            "-filter:a",
            "atempo=1.25",
            VOICE_FILE_FAST,
        ],
        check=True,
    )


def choose_background():
    files = glob.glob(os.path.join(BACKGROUND_FOLDER, "*.mp3"))
    files = [
        file
        for file in files
        if os.path.basename(file)
        not in ("voice_raw.mp3", "voice.mp3", "test_digest.mp3")
    ]

    if not files:
        return None

    return random.choice(files)


def mix_audio():
    background_file = choose_background()

    if not background_file:
        print("Фоновая музыка не найдена. Создаю только голос.")
        os.replace(VOICE_FILE_FAST, OUTPUT_FILE)
        return

    print(f"Выбран фон: {background_file}")

    voice = AudioSegment.from_file(VOICE_FILE_FAST, format="mp3")
    music = AudioSegment.from_file(background_file, format="mp3")

    if len(music) < len(voice):
        repeats = (len(voice) // len(music)) + 1
        music = music * repeats

    music = music[: len(voice)]
    music = music - 6

    mixed = music.overlay(voice)
    mixed.export(OUTPUT_FILE, format="mp3", bitrate="128k")

    print(f"Готово: {OUTPUT_FILE}")


def main():
    create_voice()
    make_voice_faster()
    mix_audio()


if __name__ == "__main__":
    main()
