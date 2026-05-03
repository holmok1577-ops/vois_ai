"""
Telegram бот для голосового помощника.
Обрабатывает голосовые сообщения и текстовые запросы.
"""

import asyncio
import logging
import os
import sys
from io import BytesIO

from dotenv import load_dotenv
from pathlib import Path
from pydub import AudioSegment
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram import InputFile
from telegram.error import BadRequest

# Добавляем родительскую директорию в путь
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from voice_agent_core import VoiceAgentCore, sanitize_tts_text, lpcm_to_wav_bytes

# Загрузка переменных окружения из корня проекта
project_root = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=project_root / ".env", override=True)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
YANDEX_CLOUD_API_KEY = os.getenv("YANDEX_CLOUD_API_KEY", "")
YANDEX_CLOUD_FOLDER_ID = os.getenv("YANDEX_CLOUD_FOLDER_ID", "")
SPEECHKIT_STT_ENDPOINT = os.getenv("SPEECHKIT_STT_ENDPOINT", "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize")
SPEECHKIT_STT_MODE = os.getenv("SPEECHKIT_STT_MODE", "batch")
SPEECHKIT_STT_GRPC_ENDPOINT = os.getenv("SPEECHKIT_STT_GRPC_ENDPOINT", "stt.api.cloud.yandex.net:443")
SPEECHKIT_TTS_ENDPOINT = os.getenv("SPEECHKIT_TTS_ENDPOINT", "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize")
LLM_API_ENDPOINT = os.getenv("LLM_API_ENDPOINT", "https://llm.api.cloud.yandex.net/llm/v1/completion")
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "")
VOICE = "jane"
IN_RATE = 16000
OUT_RATE = 16000

# Хранилище агентов для каждого пользователя
user_agents: dict[int, VoiceAgentCore] = {}


def convert_ogg_to_pcm16(ogg_data: bytes) -> bytes:
    """Конвертирует OGG аудио в PCM16."""
    try:
        # Загружаем OGG файл
        audio = AudioSegment.from_ogg(BytesIO(ogg_data))
        
        # Конвертируем в моно, 16kHz, 16-bit PCM
        audio = audio.set_channels(1)
        audio = audio.set_frame_rate(IN_RATE)
        audio = audio.set_sample_width(2)  # 16-bit = 2 bytes
        
        # Экспортируем в raw PCM
        pcm_data = audio.raw_data
        return pcm_data
    except Exception as e:
        logger.error(f"Ошибка конвертации аудио: {e}")
        raise


def convert_pcm16_to_ogg(pcm_data: bytes, sample_rate: int = OUT_RATE) -> bytes:
    """Конвертирует PCM16 в OGG (Opus).
    Вход: PCM16 с частотой sample_rate (обычно 16000). Перед экспортом ресемплим до 48000 Гц.
    """
    try:
        # Создаем AudioSegment из raw PCM
        audio = AudioSegment(
            pcm_data,
            frame_rate=sample_rate,
            channels=1,
            sample_width=2
        )
        # Ресемплим до 48000 Гц для лучшей совместимости с Opus/Telegram
        audio = audio.set_frame_rate(48000)
        
        # Экспортируем в OGG
        ogg_buffer = BytesIO()
        audio.export(ogg_buffer, format="ogg", codec="libopus")
        ogg_buffer.seek(0)
        return ogg_buffer.read()
    except Exception as e:
        logger.error(f"Ошибка конвертации в OGG: {e}")
        raise


async def get_or_create_agent(user_id: int) -> VoiceAgentCore:
    """Получает или создает агента для пользователя."""
    if user_id not in user_agents:
        agent = VoiceAgentCore(
            api_key=YANDEX_CLOUD_API_KEY,
            folder_id=YANDEX_CLOUD_FOLDER_ID,
            stt_endpoint=SPEECHKIT_STT_ENDPOINT,
            tts_endpoint=SPEECHKIT_TTS_ENDPOINT,
            llm_endpoint=LLM_API_ENDPOINT,
            vector_store_id=VECTOR_STORE_ID,
            voice=VOICE,
            in_rate=IN_RATE,
            out_rate=OUT_RATE,
            stt_mode=SPEECHKIT_STT_MODE,
            stt_grpc_endpoint=SPEECHKIT_STT_GRPC_ENDPOINT
        )
        await agent.initialize()
        user_agents[user_id] = agent
        logger.info(f"Создан агент для пользователя {user_id}")
    return user_agents[user_id]


async def cleanup_agent(user_id: int):
    """Очищает агента пользователя."""
    if user_id in user_agents:
        agent = user_agents[user_id]
        await agent.cleanup()
        del user_agents[user_id]
        logger.info(f"Удален агент пользователя {user_id}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    await update.message.reply_text(
        "👋 Привет! Я голосовой помощник.\n\n"
        "Отправь мне:\n"
        "• 🎤 Голосовое сообщение - для голосового общения\n"
        "• 📝 Текстовое сообщение - для текстового общения\n\n"
        "Команды:\n"
        "/start - Начать работу\n"
        "/help - Показать справку\n"
        "/stop - Остановить сессию"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    await update.message.reply_text(
        "📖 Справка по использованию:\n\n"
        "1. Отправь голосовое сообщение - я отвечу голосом\n"
        "2. Отправь текстовое сообщение - я отвечу текстом\n"
        "3. Используй команду /stop для остановки текущей сессии\n\n"
        "Я могу отвечать на вопросы, помогать с задачами и многое другое!"
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /stop."""
    user_id = update.effective_user.id
    await cleanup_agent(user_id)
    await update.message.reply_text("✅ Сессия остановлена. Используйте /start для начала новой сессии.")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает голосовые сообщения."""
    user_id = update.effective_user.id
    voice = update.message.voice
    
    try:
        # Отправляем статус обработки
        status_message = await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...")
        
        # Получаем файл голосового сообщения
        file = await context.bot.get_file(voice.file_id)
        
        # Скачиваем файл
        ogg_data = BytesIO()
        await file.download_to_memory(ogg_data)
        ogg_data.seek(0)
        ogg_bytes = ogg_data.read()
        
        # Конвертируем OGG в PCM16
        pcm_data = convert_ogg_to_pcm16(ogg_bytes)
        
        # Получаем или создаем агента
        agent = await get_or_create_agent(user_id)
        
        # БЭТЧ-обработка для Telegram: ASR -> LLM -> TTS без стриминга
        # 1) Распознаём речь
        text = await agent.asr.recognize(pcm_data)
        if text:
            try:
                await status_message.edit_text(f"🎤 Распознано: {text}\n\n💭 Думаю...")
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
        else:
            await status_message.edit_text("❌ Не удалось распознать речь.")
            return

        # 2) Генерируем ответ
        response_text = await agent.llm.generate_response(text)
        if response_text:
            try:
                await status_message.edit_text(f"💬 Ответ:\n\n{response_text}")
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise

        # 3) Синтез речи
        tts_text = sanitize_tts_text(response_text)
        audio_lpcm = await agent.tts.synthesize(tts_text, agent.out_rate)
        if audio_lpcm:
            # Заворачиваем LPCM в WAV для конвертации в OGG/Opus
            wav_bytes = lpcm_to_wav_bytes(audio_lpcm, agent.out_rate, channels=1, sample_width=2)
            wav_bio = BytesIO(wav_bytes)
            try:
                seg = AudioSegment.from_file(wav_bio, format="wav")
                seg = seg.set_channels(1).set_frame_rate(48000).set_sample_width(2)
                ogg_buffer = BytesIO()
                seg.export(ogg_buffer, format="ogg", codec="libopus")
                ogg_bytes = ogg_buffer.getvalue()
            except Exception as e:
                logger.error(f"Ошибка конвертации WAV->OGG: {e}")
                ogg_bytes = b""
            # Отправляем голос
            if ogg_bytes:
                bio = BytesIO(ogg_bytes)
                bio.name = "voice.ogg"
                bio.seek(0)
                try:
                    await update.message.reply_voice(
                        voice=InputFile(bio, filename="voice.ogg"),
                        duration=len(audio_lpcm) // (agent.out_rate * 2)
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки голосового ответа: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки голосового сообщения: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения."""
    user_id = update.effective_user.id
    text = update.message.text
    
    try:
        # Отправляем статус обработки
        status_message = await update.message.reply_text("💭 Думаю...")
        
        # Получаем или создаем агента
        agent = await get_or_create_agent(user_id)
        
        # БЭТЧ-обработка текста: LLM -> TTS
        response_text = await agent.llm.generate_response(text)
        if response_text:
            try:
                await status_message.edit_text(f"💬 Ответ:\n\n{response_text}")
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
        else:
            await status_message.edit_text("❌ Не удалось получить ответ.")
            return
        
        # Синтез и отправка голоса (опционально)
        tts_text = sanitize_tts_text(response_text)
        audio_lpcm = await agent.tts.synthesize(tts_text, agent.out_rate)
        if audio_lpcm:
            wav_bytes = lpcm_to_wav_bytes(audio_lpcm, agent.out_rate, channels=1, sample_width=2)
            wav_bio = BytesIO(wav_bytes)
            try:
                seg = AudioSegment.from_file(wav_bio, format="wav")
                seg = seg.set_channels(1).set_frame_rate(48000).set_sample_width(2)
                ogg_buffer = BytesIO()
                seg.export(ogg_buffer, format="ogg", codec="libopus")
                ogg_bytes = ogg_buffer.getvalue()
                bio = BytesIO(ogg_bytes)
                bio.name = "voice.ogg"
                bio.seek(0)
                await update.message.reply_voice(voice=InputFile(bio, filename="voice.ogg"),
                                                duration=len(audio_lpcm)//(agent.out_rate*2))
            except Exception as e:
                logger.error(f"Ошибка конвертации/отправки голоса: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки текстового сообщения: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки: {str(e)}")


def main():
    """Основная функция запуска бота."""
    # Проверка конфигурации
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не установлен в .env файле")
        sys.exit(1)
    
    if not YANDEX_CLOUD_API_KEY:
        logger.error("YANDEX_CLOUD_API_KEY не установлен в .env файле")
        sys.exit(1)
    
    if not YANDEX_CLOUD_FOLDER_ID:
        logger.error("YANDEX_CLOUD_FOLDER_ID не установлен в .env файле")
        sys.exit(1)
    
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Запускаем бота
    logger.info("Запуск Telegram бота...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


