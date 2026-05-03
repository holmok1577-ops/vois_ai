"""
Веб-сервер для голосового помощника.
Использует FastAPI для создания веб-интерфейса и WebSocket для реального времени.
"""

import asyncio
import base64
import io
import json
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Добавляем родительскую директорию в путь для импорта
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from voice_agent_core import VoiceAgentCore
from pydub import AudioSegment
from shutil import which

# Загрузка переменных окружения из корня проекта
project_root = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=project_root / ".env", override=True)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка путей ffmpeg для pydub, если доступны в PATH
ffmpeg_path = which("ffmpeg")
ffprobe_path = which("ffprobe")
if ffmpeg_path:
    AudioSegment.converter = ffmpeg_path
if ffprobe_path:
    AudioSegment.ffprobe = ffprobe_path

# Конфигурация
YANDEX_CLOUD_API_KEY = os.getenv("YANDEX_CLOUD_API_KEY", "")
YANDEX_CLOUD_FOLDER_ID = os.getenv("YANDEX_CLOUD_FOLDER_ID", "")
SPEECHKIT_STT_ENDPOINT = os.getenv("SPEECHKIT_STT_ENDPOINT", "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize")
SPEECHKIT_STT_MODE = os.getenv("SPEECHKIT_STT_MODE", "batch")
SPEECHKIT_STT_GRPC_ENDPOINT = os.getenv("SPEECHKIT_STT_GRPC_ENDPOINT", "stt.api.cloud.yandex.net:443")
SPEECHKIT_TTS_ENDPOINT = os.getenv("SPEECHKIT_TTS_ENDPOINT", "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize")
LLM_API_ENDPOINT = os.getenv("LLM_API_ENDPOINT", "https://llm.api.cloud.yandex.net/llm/v1/completion")
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "")
IN_RATE = 16000
OUT_RATE = 16000
VOICE = "jane"

# Хранилище активных соединений
active_connections: dict[str, VoiceAgentCore] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Startup
    logger.info("Запуск приложения...")
    yield
    # Shutdown
    logger.info("Завершение работы сервера...")
    for client_id, agent in list(active_connections.items()):
        try:
            await agent.cleanup()
        except Exception as e:
            logger.error(f"Ошибка при очистке агента {client_id}: {e}")
    active_connections.clear()


# Создание FastAPI приложения с lifespan
app = FastAPI(title="Голосовой помощник", lifespan=lifespan)


def b64_encode(data: bytes) -> str:
    """Кодирует данные в Base64."""
    return base64.b64encode(data).decode('utf-8')


def b64_decode(data: str) -> bytes:
    """Декодирует данные из Base64."""
    return base64.b64decode(data)


@app.get("/")
async def get_index():
    """Возвращает HTML страницу с интерфейсом."""
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    return FileResponse(
        html_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket эндпоинт для обработки голосового взаимодействия."""
    await websocket.accept()
    logger.info(f"Клиент {client_id} подключен")
    
    # Создаем ядро голосового агента
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
    
    active_connections[client_id] = agent
    # Буфер для поступающих аудио-чанков (WebM/Opus из браузера)
    webm_buffer = bytearray()
    
    try:
        # Инициализируем агента
        await agent.initialize()
        
        # Запускаем задачу для отправки ответов клиенту
        async def send_responses():
            try:
                async for message in agent.get_responses():
                    await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Ошибка отправки ответов: {e}")
        
        response_task = asyncio.create_task(send_responses())
        
        # Обрабатываем входящие сообщения
        while True:
            try:
                data = await websocket.receive_json()
                message_type = data.get("type")
                
                if message_type == "start":
                    # Сброс и калибровка VAD при старте записи
                    try:
                        await agent.reset_vad()
                    except Exception as e:
                        logger.error(f"Ошибка reset_vad: {e}")
                    await websocket.send_json({"type": "status", "status": "started"})

                elif message_type == "audio_pcm":
                    # Прямая передача PCM16 16k (Base64)
                    audio_b64 = data.get("audio", "")
                    if audio_b64:
                        pcm_bytes = b64_decode(audio_b64)
                        if agent.stt_mode == "streaming":
                            await agent.process_audio(pcm_bytes)
                        else:
                            asyncio.create_task(agent.process_audio(pcm_bytes))

                elif message_type == "audio":
                    # Получаем аудио данные (Base64) из браузера (webm/opus)
                    audio_b64 = data.get("audio", "")
                    if audio_b64:
                        # Накопим байты WebM/Opus в буфере, так как малые чанки не декодируются корректно
                        webm_buffer.extend(b64_decode(audio_b64))
                        # Порог для попытки декодирования (~80KB)
                        if len(webm_buffer) >= 80_000:
                            try:
                                # Сначала пробуем webm
                                seg = AudioSegment.from_file(io.BytesIO(bytes(webm_buffer)), format="webm")
                            except Exception as e_webm:
                                logger.warning(f"WebM не декодирован, пробуем OGG: {e_webm}")
                                try:
                                    seg = AudioSegment.from_file(io.BytesIO(bytes(webm_buffer)), format="ogg")
                                except Exception as e_ogg:
                                    logger.error(f"Ошибка декодирования WebM/OGG Opus: {e_ogg}")
                                    # Не очищаем буфер — дождёмся больше данных; ограничим размер
                                    if len(webm_buffer) > 200_000:
                                        webm_buffer[:] = webm_buffer[-200_000:]
                                    # Не поднимаем исключение — продолжим накапливать данные
                                    seg = None
                            if not seg:
                                # Недостаточно данных для декодирования — ждём следующие чанки
                                continue
                            # Если дошли сюда — seg успешно создан
                            seg = seg.set_frame_rate(IN_RATE).set_channels(1).set_sample_width(2)
                            pcm_bytes = seg.raw_data
                            # Отправляем PCM16 16k в ядро (оно уже буферизует/троттлит ASR)
                            asyncio.create_task(agent.process_audio(pcm_bytes))
                            webm_buffer.clear()
                
                elif message_type == "text":
                    # Текстовый запрос (альтернатива голосу)
                    text = data.get("text", "")
                    if text:
                        # Создаем задачу для асинхронной обработки текста
                        asyncio.create_task(agent.process_text(text))
                elif message_type == "eou":
                    # Конец одной голосовой фразы без выключения микрофона.
                    if agent.stt_mode == "streaming":
                        try:
                            await agent.finish_audio()
                        except Exception as e:
                            logger.error(f"Ошибка завершения streaming STT фразы: {e}")
                        await websocket.send_json({"type": "status", "status": "listening"})
                elif message_type == "start":
                    # Начало записи: очистим буфер и уведомим клиента о статусе
                    webm_buffer.clear()
                    await websocket.send_json({"type": "status", "status": "started"})
                elif message_type == "stop":
                    if agent.stt_mode == "streaming":
                        try:
                            await agent.finish_audio()
                        except Exception as e:
                            logger.error(f"Ошибка завершения streaming STT: {e}")
                            try:
                                await agent.streaming_asr.reset_session()
                            except Exception:
                                pass
                        await websocket.send_json({"type": "status", "status": "stopped"})
                        continue

                    # При остановке записи попытаемся декодировать остаток буфера
                    if webm_buffer:
                        try:
                            try:
                                seg = AudioSegment.from_file(io.BytesIO(bytes(webm_buffer)), format="webm")
                            except Exception:
                                seg = AudioSegment.from_file(io.BytesIO(bytes(webm_buffer)), format="ogg")
                            seg = seg.set_frame_rate(IN_RATE).set_channels(1).set_sample_width(2)
                            pcm_bytes = seg.raw_data
                            asyncio.create_task(agent.process_audio(pcm_bytes))
                        except Exception as e:
                            logger.error(f"Ошибка финального декодирования WebM/OGG Opus: {e}")
                        finally:
                            webm_buffer.clear()
                
            except WebSocketDisconnect:
                logger.info(f"Клиент {client_id} отключен")
                break
            except Exception as e:
                # Не шлём ошибки в UI, чтобы не мешать работе — только логируем
                logger.error(f"Ошибка обработки сообщения: {e}")
        
        # Отменяем задачу отправки ответов
        response_task.cancel()
        try:
            await response_task
        except asyncio.CancelledError:
            pass
            
    except Exception as e:
        logger.error(f"Ошибка в WebSocket соединении: {e}")
    finally:
        # Очищаем соединение
        await agent.cleanup()
        if client_id in active_connections:
            del active_connections[client_id]
        logger.info(f"Соединение с клиентом {client_id} закрыто")


if __name__ == "__main__":
    import uvicorn
    
    # Проверка конфигурации
    if not YANDEX_CLOUD_API_KEY:
        logger.error("YANDEX_CLOUD_API_KEY не установлен")
        sys.exit(1)
    if not YANDEX_CLOUD_FOLDER_ID:
        logger.error("YANDEX_CLOUD_FOLDER_ID не установлен")
        sys.exit(1)
    
    # Запуск сервера
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=True
    )
