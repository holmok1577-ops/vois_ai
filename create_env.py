"""
Скрипт для создания файла .env из env.example
"""

import shutil
from pathlib import Path

def create_env_file():
    """Создает файл .env из env.example"""
    script_dir = Path(__file__).parent.absolute()
    env_path = script_dir / ".env"
    env_example_path = script_dir / "env.example"
    
    if env_path.exists():
        print(f"⚠️  Файл .env уже существует: {env_path}")
        response = input("Перезаписать? (y/n): ")
        if response.lower() != 'y':
            print("Отменено.")
            return False
    
    if not env_example_path.exists():
        print(f"❌ Файл env.example не найден: {env_example_path}")
        return False
    
    try:
        shutil.copy(env_example_path, env_path)
        print(f"✅ Файл .env создан: {env_path}")
        print("\n⚠️  ВАЖНО: Заполните следующие переменные в файле .env:")
        print("   - YANDEX_CLOUD_API_KEY")
        print("   - YANDEX_CLOUD_FOLDER_ID")
        print("   - SPEECHKIT_STT_ENDPOINT")
        print("   - SPEECHKIT_TTS_ENDPOINT")
        print("   - LLM_API_ENDPOINT")
        print("   - TELEGRAM_BOT_TOKEN (опционально, только для Telegram бота)")
        print("\nОткройте файл .env и заполните необходимые значения.")
        return True
    except Exception as e:
        print(f"❌ Ошибка при создании файла .env: {e}")
        return False

if __name__ == "__main__":
    create_env_file()
