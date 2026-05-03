"""
Скрипт для запуска всех вариантов голосового помощника одновременно.
Запускает веб-интерфейс, Telegram бота и консольное приложение.
"""

import os
import sys
import subprocess
import time
import signal
import threading
from pathlib import Path
import shutil

# Цвета для вывода
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'

def print_colored(message, color=Colors.RESET):
    """Печатает цветное сообщение."""
    print(f"{color}{message}{Colors.RESET}")

def check_env_file():
    """Проверяет наличие и корректность .env файла."""
    # Получаем директорию скрипта
    script_dir = Path(__file__).parent.absolute()
    env_path = script_dir / ".env"
    env_example_path = script_dir / "env.example"
    
    # Проверяем наличие .env файла несколькими способами
    env_exists = False
    
    # Способ 1: Проверка через Path.exists()
    if env_path.exists():
        env_exists = True
        print_colored(f"✅ Файл .env найден: {env_path}", Colors.GREEN)
    else:
        # Способ 2: Проверка через os.path.exists() (для скрытых файлов)
        env_str_path = str(env_path)
        if os.path.exists(env_str_path):
            env_exists = True
            print_colored(f"✅ Файл .env найден (через os.path): {env_path}", Colors.GREEN)
        else:
            # Способ 3: Попытка открыть файл напрямую
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    f.read(1)  # Попытка прочитать хотя бы один символ
                env_exists = True
                print_colored(f"✅ Файл .env найден (доступен для чтения): {env_path}", Colors.GREEN)
            except FileNotFoundError:
                env_exists = False
            except Exception as e:
                # Файл может существовать, но быть недоступным
                print_colored(f"⚠️  Файл .env возможно существует, но недоступен: {e}", Colors.YELLOW)
                env_exists = False
    
    if not env_exists:
        print_colored("❌ Файл .env не найден!", Colors.RED)
        print_colored(f"Ожидаемый путь: {env_path}", Colors.YELLOW)
        print_colored(f"Текущая рабочая директория: {os.getcwd()}", Colors.CYAN)
        
        # Пытаемся создать .env из env.example
        if env_example_path.exists():
            print_colored("Попытка создать .env из env.example...", Colors.YELLOW)
            try:
                import shutil
                shutil.copy(env_example_path, env_path)
                print_colored("✅ Файл .env создан из env.example", Colors.GREEN)
                print_colored("⚠️  ВАЖНО: Заполните YANDEX_CLOUD_API_KEY и YANDEX_CLOUD_FOLDER_ID в файле .env", Colors.YELLOW)
                print_colored(f"Файл находится по пути: {env_path}", Colors.CYAN)
                return False  # Возвращаем False, так как нужно заполнить данные
            except Exception as e:
                print_colored(f"❌ Не удалось создать .env: {e}", Colors.RED)
                print_colored("Создайте файл .env вручную на основе env.example", Colors.YELLOW)
                return False
        else:
            print_colored("Файл env.example не найден!", Colors.RED)
            return False
    
    # Проверяем наличие обязательных переменных
    from dotenv import load_dotenv
    # Загружаем .env из директории скрипта (несколько попыток)
    try:
        # Попытка 1: Загрузка с явным путем
        load_dotenv(dotenv_path=env_path, override=True)
    except Exception as e:
        print_colored(f"⚠️  Предупреждение при загрузке .env: {e}", Colors.YELLOW)
        # Попытка 2: Загрузка из текущей директории
        try:
            load_dotenv(override=True)
        except Exception as e2:
            print_colored(f"⚠️  Предупреждение при загрузке .env из текущей директории: {e2}", Colors.YELLOW)
    
    # Также пытаемся загрузить из директории скрипта явно
    old_cwd = os.getcwd()
    try:
        os.chdir(script_dir)
        load_dotenv(override=True)
    finally:
        os.chdir(old_cwd)
    
    api_key = os.getenv("YANDEX_CLOUD_API_KEY", "")
    folder_id = os.getenv("YANDEX_CLOUD_FOLDER_ID", "")
    stt_endpoint = os.getenv("SPEECHKIT_STT_ENDPOINT", "")
    tts_endpoint = os.getenv("SPEECHKIT_TTS_ENDPOINT", "")
    llm_endpoint = os.getenv("LLM_API_ENDPOINT", "")
    
    if not api_key or api_key == "your_api_key_here" or api_key.strip() == "":
        print_colored("❌ YANDEX_CLOUD_API_KEY не установлен в .env", Colors.RED)
        print_colored(f"Откройте файл .env: {env_path}", Colors.YELLOW)
        print_colored("И заполните YANDEX_CLOUD_API_KEY=ваш_ключ", Colors.YELLOW)
        print_colored(f"Текущее значение: '{api_key}'", Colors.CYAN)
        return False
    
    if not folder_id or folder_id == "your_folder_id_here" or folder_id.strip() == "":
        print_colored("❌ YANDEX_CLOUD_FOLDER_ID не установлен в .env", Colors.RED)
        print_colored(f"Откройте файл .env: {env_path}", Colors.YELLOW)
        print_colored("И заполните YANDEX_CLOUD_FOLDER_ID=ваш_id", Colors.YELLOW)
        print_colored(f"Текущее значение: '{folder_id}'", Colors.CYAN)
        return False
    
    if not stt_endpoint or stt_endpoint.strip() == "":
        print_colored("❌ SPEECHKIT_STT_ENDPOINT не установлен в .env", Colors.RED)
        print_colored(f"Откройте файл .env: {env_path}", Colors.YELLOW)
        print_colored("И заполните SPEECHKIT_STT_ENDPOINT=https://stt.api.cloud.yandex.net/speech/v1/stt:recognize", Colors.YELLOW)
        print_colored(f"Текущее значение: '{stt_endpoint}'", Colors.CYAN)
        return False
    
    if not tts_endpoint or tts_endpoint.strip() == "":
        print_colored("❌ SPEECHKIT_TTS_ENDPOINT не установлен в .env", Colors.RED)
        print_colored(f"Откройте файл .env: {env_path}", Colors.YELLOW)
        print_colored("И заполните SPEECHKIT_TTS_ENDPOINT=https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize", Colors.YELLOW)
        print_colored(f"Текущее значение: '{tts_endpoint}'", Colors.CYAN)
        return False
    
    if not llm_endpoint or llm_endpoint.strip() == "":
        print_colored("❌ LLM_API_ENDPOINT не установлен в .env", Colors.RED)
        print_colored(f"Откройте файл .env: {env_path}", Colors.YELLOW)
        print_colored("И заполните LLM_API_ENDPOINT=https://llm.api.cloud.yandex.net/llm/v1/completion", Colors.YELLOW)
        print_colored(f"Текущее значение: '{llm_endpoint}'", Colors.CYAN)
        return False
    
    print_colored("✅ Файл .env настроен корректно", Colors.GREEN)
    print_colored(f"📁 Путь к .env: {env_path}", Colors.CYAN)
    print_colored(f"🔑 API Key: {api_key[:10]}... (скрыто)", Colors.CYAN)
    print_colored(f"📂 Folder ID: {folder_id}", Colors.CYAN)
    print_colored(f"🎤 STT Endpoint: {stt_endpoint}", Colors.CYAN)
    print_colored(f"📢 TTS Endpoint: {tts_endpoint}", Colors.CYAN)
    print_colored(f"🤖 LLM Endpoint: {llm_endpoint}", Colors.CYAN)
    return True

def run_web_interface():
    """Запускает веб-интерфейс."""
    try:
        print_colored("🌐 Запуск веб-интерфейса...", Colors.CYAN)
        web_dir = Path("web_interface")
        if not web_dir.exists():
            print_colored("❌ Директория web_interface не найдена", Colors.RED)
            return None
        
        process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=web_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print_colored("✅ Веб-интерфейс запущен: http://localhost:8000", Colors.GREEN)
        return process
    except Exception as e:
        print_colored(f"❌ Ошибка запуска веб-интерфейса: {e}", Colors.RED)
        return None

def run_telegram_bot():
    """Запускает Telegram бота."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        if not bot_token or bot_token == "":
            print_colored("⚠️  TELEGRAM_BOT_TOKEN не установлен, пропускаем Telegram бота", Colors.YELLOW)
            return None
        
        print_colored("📱 Запуск Telegram бота...", Colors.CYAN)
        bot_dir = Path("telegram_bot")
        if not bot_dir.exists():
            print_colored("❌ Директория telegram_bot не найдена", Colors.RED)
            return None
        
        process = subprocess.Popen(
            [sys.executable, "bot.py"],
            cwd=bot_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print_colored("✅ Telegram бот запущен", Colors.GREEN)
        return process
    except Exception as e:
        print_colored(f"❌ Ошибка запуска Telegram бота: {e}", Colors.RED)
        return None


def print_logs(process, name, color):
    """Печатает логи процесса."""
    if process is None:
        return
    
    def log_stdout():
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                if line:
                    print_colored(f"[{name}] {line.strip()}", color)
    
    def log_stderr():
        if process.stderr:
            for line in iter(process.stderr.readline, ''):
                if line:
                    print_colored(f"[{name} ERROR] {line.strip()}", Colors.RED)
    
    thread_stdout = threading.Thread(target=log_stdout, daemon=True)
    thread_stderr = threading.Thread(target=log_stderr, daemon=True)
    thread_stdout.start()
    thread_stderr.start()

def main():
    """Основная функция."""
    # Переходим в директорию скрипта
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    print_colored("=" * 60, Colors.CYAN)
    print_colored("🚀 Запуск всех вариантов голосового помощника", Colors.CYAN)
    print_colored("=" * 60, Colors.CYAN)
    print_colored(f"📁 Рабочая директория: {script_dir}", Colors.CYAN)
    print()
    
    # Проверяем .env файл
    if not check_env_file():
        print_colored("\n⚠️  Исправьте ошибки в .env файле и попробуйте снова", Colors.YELLOW)
        print_colored(f"💡 Файл .env должен находиться в: {script_dir / '.env'}", Colors.CYAN)
        return
    
    print()
    processes = []
    
    # Запускаем веб-интерфейс
    web_process = run_web_interface()
    if web_process:
        processes.append(("Веб-интерфейс", web_process, Colors.BLUE))
        time.sleep(2)  # Даем время на запуск
    
    # Запускаем Telegram бота
    telegram_process = run_telegram_bot()
    if telegram_process:
        processes.append(("Telegram бот", telegram_process, Colors.GREEN))
        time.sleep(2)
    
    if not processes:
        print_colored("❌ Не удалось запустить ни одного варианта", Colors.RED)
        return
    
    print()
    print_colored("=" * 60, Colors.CYAN)
    print_colored("✅ Все варианты запущены!", Colors.GREEN)
    print_colored("=" * 60, Colors.CYAN)
    print()
    print_colored("Доступные варианты:", Colors.CYAN)
    if web_process:
        print_colored("  🌐 Веб-интерфейс: http://localhost:8000", Colors.BLUE)
    if telegram_process:
        print_colored("  📱 Telegram бот: найдите вашего бота в Telegram", Colors.GREEN)
    print()
    print_colored("Нажмите Ctrl+C для остановки всех процессов", Colors.YELLOW)
    print()
    
    # Обработка сигнала прерывания
    def signal_handler(sig, frame):
        print_colored("\n\n🛑 Остановка всех процессов...", Colors.YELLOW)
        for name, process, _ in processes:
            if process and process.poll() is None:
                print_colored(f"Остановка {name}...", Colors.YELLOW)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        print_colored("✅ Все процессы остановлены", Colors.GREEN)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Запускаем потоки для вывода логов
    log_threads = []
    for name, process, color in processes:
        if process:
            thread = threading.Thread(
                target=print_logs,
                args=(process, name, color),
                daemon=True
            )
            thread.start()
            log_threads.append(thread)
    
    # Ждем завершения процессов
    try:
        while True:
            # Проверяем, что процессы еще работают
            alive_processes = [p for _, p, _ in processes if p and p.poll() is None]
            if not alive_processes:
                print_colored("⚠️  Все процессы завершились", Colors.YELLOW)
                break
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_colored("\n\n🛑 Прервано пользователем", Colors.YELLOW)
        sys.exit(0)
    except Exception as e:
        print_colored(f"\n❌ Критическая ошибка: {e}", Colors.RED)
        import traceback
        traceback.print_exc()
        sys.exit(1)
