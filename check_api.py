"""
Скрипт для проверки подключения к Yandex Cloud Realtime API
"""

import asyncio
import os
import sys
from pathlib import Path

# Добавляем родительскую директорию в путь
parent_dir = Path(__file__).parent.absolute()
sys.path.insert(0, str(parent_dir))

from dotenv import load_dotenv
import aiohttp

async def check_api_connection():
    """Проверяет подключение к Yandex Cloud Realtime API."""
    # Загружаем переменные окружения
    env_path = parent_dir / ".env"
    load_dotenv(dotenv_path=env_path)
    
    api_key = os.getenv("YANDEX_CLOUD_API_KEY", "")
    folder_id = os.getenv("YANDEX_CLOUD_FOLDER_ID", "")
    ws_url = "wss://llm.api.cloud.yandex.net/llm/v1/realtime"
    
    print("=" * 60)
    print("Проверка подключения к Yandex Cloud Realtime API")
    print("=" * 60)
    print()
    
    # Проверка переменных окружения
    print("1. Проверка переменных окружения:")
    if not api_key or api_key == "your_api_key_here":
        print("   ❌ YANDEX_CLOUD_API_KEY не установлен")
        return False
    else:
        print(f"   ✅ YANDEX_CLOUD_API_KEY установлен: {api_key[:10]}...")
    
    if not folder_id or folder_id == "your_folder_id_here":
        print("   ❌ YANDEX_CLOUD_FOLDER_ID не установлен")
        return False
    else:
        print(f"   ✅ YANDEX_CLOUD_FOLDER_ID установлен: {folder_id}")
    
    print()
    print("2. Попытка подключения к API:")
    print(f"   URL: {ws_url}")
    print(f"   Метод аутентификации: Api-Key")
    print()
    
    headers = {
        "Authorization": f"Api-Key {api_key}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            print("   Попытка установить WebSocket соединение...")
            try:
                async with session.ws_connect(
                    ws_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as ws:
                    print("   ✅ Успешное подключение к Realtime API!")
                    print()
                    print("3. Проверка отправки сообщения:")
                    
                    # Попытка отправить тестовое сообщение
                    test_message = {
                        "type": "session.update",
                        "session": {
                            "model": "general",
                            "audio": {
                                "input_audio_format": "pcm16",
                                "output_audio_format": "pcm16",
                                "input_audio_sample_rate": 16000,
                                "output_audio_sample_rate": 24000,
                                "voice": "jane"
                            }
                        }
                    }
                    
                    import json
                    await ws.send_str(json.dumps(test_message))
                    print("   ✅ Сообщение отправлено успешно")
                    
                    # Ждем ответа
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                        print(f"   ✅ Получен ответ: {msg.type}")
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            print(f"   Данные ответа: {json.dumps(data, indent=2, ensure_ascii=False)}")
                    except asyncio.TimeoutError:
                        print("   ⚠️  Таймаут при ожидании ответа (это может быть нормально)")
                    
                    return True
                    
            except aiohttp.client_exceptions.WSServerHandshakeError as e:
                print(f"   ❌ Ошибка подключения: {e}")
                print(f"   Статус HTTP: {e.status if hasattr(e, 'status') else 'неизвестно'}")
                print(f"   Сообщение: {e.message if hasattr(e, 'message') else 'неизвестно'}")
                print()
                print("   Возможные причины:")
                print("   1. Неправильный API ключ")
                print("   2. Неправильный Folder ID")
                print("   3. У сервисного аккаунта нет прав доступа к Realtime API")
                print("   4. API недоступен в вашем регионе")
                print("   5. Неправильный URL API")
                print()
                print("   Рекомендации:")
                print("   - Проверьте API ключ в Yandex Cloud Console")
                print("   - Убедитесь, что сервисный аккаунт имеет роль ai.languageModels.user")
                print("   - Проверьте, что Realtime API доступен в вашем каталоге")
                print("   - Проверьте актуальную документацию Yandex Cloud")
                return False
            except Exception as e:
                print(f"   ❌ Неожиданная ошибка: {e}")
                print(f"   Тип ошибки: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                return False
                
    except Exception as e:
        print(f"   ❌ Ошибка создания сессии: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Основная функция."""
    success = await check_api_connection()
    print()
    print("=" * 60)
    if success:
        print("✅ Проверка завершена успешно!")
    else:
        print("❌ Проверка завершена с ошибками")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())

