import asyncio
import base64
import logging
import os
import sys
import threading
import time
from queue import Queue
from typing import Optional

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

# Добавляем родительскую директорию в путь для импорта
parent_dir = os.path.dirname(os.path.abspath(__file__))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Импортируем новое ядро
from voice_agent_core import VoiceAgentCore

# Конфигурация
YANDEX_CLOUD_API_KEY = os.getenv("YANDEX_CLOUD_API_KEY", "")
YANDEX_CLOUD_FOLDER_ID = os.getenv("YANDEX_CLOUD_FOLDER_ID", "")
SPEECHKIT_STT_ENDPOINT = os.getenv("SPEECHKIT_STT_ENDPOINT", "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize")
SPEECHKIT_STT_MODE = os.getenv("SPEECHKIT_STT_MODE", "batch")
SPEECHKIT_STT_GRPC_ENDPOINT = os.getenv("SPEECHKIT_STT_GRPC_ENDPOINT", "stt.api.cloud.yandex.net:443")
SPEECHKIT_TTS_ENDPOINT = os.getenv("SPEECHKIT_TTS_ENDPOINT", "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize")
LLM_API_ENDPOINT = os.getenv("LLM_API_ENDPOINT", "https://llm.api.cloud.yandex.net/llm/v1/completion")
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "")
IN_RATE = 16000  # Частота дискретизации входного аудио
OUT_RATE = 16000  # Частота дискретизации выходного аудио
VOICE = "jane"  # Голос для синтеза речи

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def float_to_pcm16(audio: np.ndarray) -> bytes:
    """Преобразует аудиоданные из float32 в PCM16."""
    audio = np.clip(audio, -1.0, 1.0)
    audio = (audio * 32767).astype(np.int16)
    return audio.tobytes()


def b64_encode(data: bytes) -> str:
    """Кодирует данные в Base64."""
    return base64.b64encode(data).decode('utf-8')


def b64_decode(data: str) -> bytes:
    """Декодирует данные из Base64."""
    return base64.b64decode(data)


def log(message: str):
    """Безопасный вывод логов."""
    logger.info(message)
    print(f"[LOG] {message}")


class AudioOut:
    """Класс для управления воспроизведением звука."""
    
    def __init__(self, sample_rate: int = OUT_RATE):
        self.sample_rate = sample_rate
        self.queue = Queue()
        self.stream = None
        self.is_playing = False
        self.stop_playback = False
        
    def start(self):
        """Запускает поток воспроизведения звука."""
        self.stop_playback = False
        self.stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='int16',
            blocksize=1024,
            callback=self._audio_callback
        )
        self.stream.start()
        log("AudioOut: начато воспроизведение звука")
        
    def stop(self):
        """Останавливает воспроизведение звука."""
        self.stop_playback = True
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        log("AudioOut: воспроизведение звука остановлено")
        
    def add_audio(self, pcm_data: bytes):
        """Добавляет аудиоданные в очередь воспроизведения."""
        self.queue.put(pcm_data)
        
    def clear_queue(self):
        """Очищает очередь воспроизведения."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except:
                pass
                
    def _audio_callback(self, outdata, frames, time_info, status):
        """Callback для sounddevice - вызывается при необходимости данных для воспроизведения."""
        if status:
            log(f"AudioOut status: {status}")
            
        if self.stop_playback:
            outdata[:] = b'\x00' * (frames * 2)  # Тишина
            return
            
        try:
            # Получаем данные из очереди, если есть
            if not self.queue.empty():
                audio_data = self.queue.get_nowait()
                # Преобразуем bytes в numpy array
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                # Обрезаем или дополняем до нужного размера
                if len(audio_array) >= frames:
                    outdata[:, 0] = audio_array[:frames]
                    self.is_playing = True
                else:
                    # Если данных меньше, дополняем нулями
                    outdata[:len(audio_array), 0] = audio_array
                    outdata[len(audio_array):, 0] = 0
                    self.is_playing = False
            else:
                # Если очередь пуста, воспроизводим тишину
                outdata[:] = 0
                self.is_playing = False
        except Exception as e:
            log(f"AudioOut callback error: {e}")
            outdata[:] = 0


class MicStreamer:
    """Класс для управления захватом аудио с микрофона."""
    
    def __init__(self, sample_rate: int = IN_RATE, queue: Optional[asyncio.Queue] = None):
        self.sample_rate = sample_rate
        self.queue = queue
        self.stream = None
        self.is_recording = False
        self.thread = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
    def start(self):
        """Запускает поток захвата аудио."""
        if self.is_recording:
            return
            
        self.is_recording = True
        self.loop = asyncio.get_running_loop()
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='float32',
            blocksize=1024,
            callback=self._audio_callback
        )
        self.stream.start()
        log("MicStreamer: начата запись с микрофона")
        
    def stop(self):
        """Останавливает запись с микрофона."""
        self.is_recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        log("MicStreamer: запись с микрофона остановлена")
        
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback для sounddevice - вызывается при получении данных с микрофона."""
        if status:
            log(f"MicStreamer status: {status}")
            
        if not self.is_recording:
            return
            
        try:
            # Преобразуем float32 в PCM16
            pcm_data = float_to_pcm16(indata[:, 0])
            # Добавляем в асинхронную очередь
            if self.queue and self.loop:
                asyncio.run_coroutine_threadsafe(
                    self.queue.put(pcm_data),
                    self.loop
                )
        except Exception as e:
            log(f"MicStreamer callback error: {e}")


async def process_audio_loop(agent: VoiceAgentCore, audio_queue: asyncio.Queue):
    """Обрабатывает аудиоданные из очереди."""
    log("Начало обработки аудио")
    try:
        while True:
            try:
                # Получаем фрагмент аудио из очереди с таймаутом
                audio_data = await asyncio.wait_for(audio_queue.get(), timeout=0.1)
                # Обрабатываем аудио через ядро
                await agent.process_audio(audio_data)
            except asyncio.TimeoutError:
                # Таймаут - это нормально, продолжаем
                continue
            except Exception as e:
                log(f"Ошибка обработки аудио: {e}")
                break
    except asyncio.CancelledError:
        log("Обработка аудио: отменено")
    except Exception as e:
        log(f"Ошибка обработки аудио: {e}")


async def handle_responses(agent: VoiceAgentCore, audio_out: AudioOut):
    """Обрабатывает ответы от голосового агента."""
    log("Начало обработки ответов")
    try:
        async for message in agent.get_responses():
            msg_type = message.get("type", "")
            
            # Распознанный текст запроса пользователя
            if msg_type == "transcription":
                text = message.get("text", "")
                if text:
                    log(f"Распознано: {text}")
            
            # Фрагмент ответа агента в текстовом виде
            elif msg_type == "text_delta":
                text = message.get("text", "")
                if text:
                    print(text, end="", flush=True)
            
            # Фрагмент ответа агента в аудиоформате
            elif msg_type == "audio_delta":
                audio_b64 = message.get("audio", "")
                if audio_b64:
                    # Декодируем аудио из Base64
                    audio_data = b64_decode(audio_b64)
                    # Добавляем в очередь воспроизведения
                    audio_out.add_audio(audio_data)
            
            # Начало нового запроса пользователя
            elif msg_type == "speech_started":
                log("Начало речи пользователя")
                # Прекращаем воспроизведение текущего ответа
                audio_out.clear_queue()
            
            # Сообщения об ошибках
            elif msg_type == "error":
                error_message = message.get("message", "Unknown error")
                log(f"Ошибка: {error_message}")
            
            # Завершение ответа
            elif msg_type == "response_done":
                log("Ответ агента завершен")
                print()  # Новая строка после вывода текста
                
    except asyncio.CancelledError:
        log("Обработка ответов: отменено")
    except Exception as e:
        log(f"Ошибка обработки ответов: {e}")


async def main():
    """Основная функция."""
    # Проверка конфигурации
    if not YANDEX_CLOUD_API_KEY:
        log("Ошибка: YANDEX_CLOUD_API_KEY не установлен")
        sys.exit(1)
    if not YANDEX_CLOUD_FOLDER_ID:
        log("Ошибка: YANDEX_CLOUD_FOLDER_ID не установлен")
        sys.exit(1)
    
    # Создаем очередь для аудиоданных с микрофона
    audio_queue = asyncio.Queue()
    
    # Создаем объекты для работы с аудио
    audio_out = AudioOut()
    mic_streamer = MicStreamer(queue=audio_queue)
    
    # Создаем голосовой агент
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
    
    try:
        # Инициализируем агент
        await agent.initialize()
        
        # Запускаем воспроизведение звука
        audio_out.start()
        
        # Запускаем запись с микрофона
        mic_streamer.start()
        
        # Запускаем фоновые задачи
        process_task = asyncio.create_task(process_audio_loop(agent, audio_queue))
        response_task = asyncio.create_task(handle_responses(agent, audio_out))
        
        # Ожидаем завершения задач
        try:
            await asyncio.gather(process_task, response_task)
        except KeyboardInterrupt:
            log("Получен сигнал прерывания (Ctrl+C)")
            process_task.cancel()
            response_task.cancel()
            await asyncio.gather(process_task, response_task, return_exceptions=True)
            
    except KeyboardInterrupt:
        log("Получен сигнал прерывания (Ctrl+C)")
    except Exception as e:
        log(f"Ошибка в main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Останавливаем запись и воспроизведение
        mic_streamer.stop()
        audio_out.stop()
        
        # Очищаем ресурсы агента
        await agent.cleanup()
        
        log("Программа завершена")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Программа прервана пользователем")
