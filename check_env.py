"""
Скрипт для проверки файла .env
Помогает диагностировать проблемы с файлом .env
"""

import os
from pathlib import Path
from dotenv import load_dotenv

def check_env():
    """Проверяет наличие и содержимое файла .env"""
    script_dir = Path(__file__).parent.absolute()
    env_path = script_dir / ".env"
    
    print("=" * 60)
    print("Проверка файла .env")
    print("=" * 60)
    print(f"Директория скрипта: {script_dir}")
    print(f"Путь к .env: {env_path}")
    print(f"Текущая рабочая директория: {os.getcwd()}")
    print()
    
    # Проверка 1: Существует ли файл
    print("Проверка 1: Существование файла")
    if env_path.exists():
        print(f"✅ Файл .env существует (Path.exists())")
    else:
        print(f"❌ Файл .env не найден (Path.exists())")
    
    if os.path.exists(str(env_path)):
        print(f"✅ Файл .env существует (os.path.exists())")
    else:
        print(f"❌ Файл .env не найден (os.path.exists())")
    
    # Проверка 2: Попытка открыть файл
    print()
    print("Проверка 2: Попытка открыть файл")
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"✅ Файл .env доступен для чтения")
            print(f"Размер файла: {len(content)} символов")
            print("Содержимое .env не выводится, чтобы не раскрывать ключи.")
    except FileNotFoundError:
        print(f"❌ Файл .env не найден (FileNotFoundError)")
    except Exception as e:
        print(f"❌ Ошибка при открытии файла: {e}")
    
    # Проверка 3: Загрузка переменных
    print()
    print("Проверка 3: Загрузка переменных окружения")
    try:
        load_dotenv(dotenv_path=env_path, override=True)
        print(f"✅ Переменные окружения загружены")
    except Exception as e:
        print(f"❌ Ошибка при загрузке переменных: {e}")
    
    # Проверка 4: Проверка значений
    print()
    print("Проверка 4: Значения переменных")
    api_key = os.getenv("YANDEX_CLOUD_API_KEY", "")
    folder_id = os.getenv("YANDEX_CLOUD_FOLDER_ID", "")
    stt_endpoint = os.getenv("SPEECHKIT_STT_ENDPOINT", "")
    stt_mode = os.getenv("SPEECHKIT_STT_MODE", "batch")
    stt_grpc_endpoint = os.getenv("SPEECHKIT_STT_GRPC_ENDPOINT", "stt.api.cloud.yandex.net:443")
    tts_endpoint = os.getenv("SPEECHKIT_TTS_ENDPOINT", "")
    llm_endpoint = os.getenv("LLM_API_ENDPOINT", "")
    vector_store_id = os.getenv("VECTOR_STORE_ID", "")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    
    print(f"YANDEX_CLOUD_API_KEY: {'✅ Установлен' if api_key and api_key != 'your_api_key_here' else '❌ Не установлен'}")
    if api_key:
        print(f"  Значение: {api_key[:10]}... (первые 10 символов)")
    else:
        print(f"  Значение: (пусто)")
    
    print(f"YANDEX_CLOUD_FOLDER_ID: {'✅ Установлен' if folder_id and folder_id != 'your_folder_id_here' else '❌ Не установлен'}")
    if folder_id:
        print(f"  Значение: {folder_id}")
    else:
        print(f"  Значение: (пусто)")
    
    print(f"SPEECHKIT_STT_ENDPOINT: {'✅ Установлен' if stt_endpoint else '❌ Не установлен'}")
    if stt_endpoint:
        print(f"  Значение: {stt_endpoint}")
    else:
        print(f"  Значение: (пусто)")

    print(f"SPEECHKIT_STT_MODE: {'✅ Установлен' if stt_mode in ('batch', 'streaming') else '❌ Некорректен'}")
    print(f"  Значение: {stt_mode}")

    print(f"SPEECHKIT_STT_GRPC_ENDPOINT: {'✅ Установлен' if stt_grpc_endpoint else '❌ Не установлен'}")
    print(f"  Значение: {stt_grpc_endpoint if stt_grpc_endpoint else '(пусто)'}")
    
    print(f"SPEECHKIT_TTS_ENDPOINT: {'✅ Установлен' if tts_endpoint else '❌ Не установлен'}")
    if tts_endpoint:
        print(f"  Значение: {tts_endpoint}")
    else:
        print(f"  Значение: (пусто)")
    
    print(f"LLM_API_ENDPOINT: {'✅ Установлен' if llm_endpoint else '❌ Не установлен'}")
    if llm_endpoint:
        print(f"  Значение: {llm_endpoint}")
    else:
        print(f"  Значение: (пусто)")
    
    print(f"VECTOR_STORE_ID: {'✅ Установлен' if vector_store_id else '⚠️  Не установлен (опционально)'}")
    if vector_store_id:
        print(f"  Значение: {vector_store_id}")
    
    print(f"TELEGRAM_BOT_TOKEN: {'✅ Установлен' if telegram_token else '⚠️  Не установлен (опционально)'}")
    if telegram_token:
        print(f"  Значение: {telegram_token[:10]}... (первые 10 символов)")
    
    print()
    print("=" * 60)
    if api_key and api_key != 'your_api_key_here' and folder_id and folder_id != 'your_folder_id_here' and stt_endpoint and tts_endpoint and llm_endpoint:
        print("✅ Файл .env настроен корректно!")
    else:
        print("❌ Файл .env не настроен корректно")
        print("Заполните YANDEX_CLOUD_API_KEY и YANDEX_CLOUD_FOLDER_ID")
    print("=" * 60)

if __name__ == "__main__":
    check_env()
