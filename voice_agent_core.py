"""
Ядро голосового агента для переиспользования в различных интеграциях.
Содержит логику работы с Yandex SpeechKit и LLM API.
"""

import asyncio
import base64
import json
import logging
import os
import io
import wave
import re
import unicodedata
import threading
import queue
from typing import AsyncGenerator, Optional
from urllib.parse import urlencode

import aiohttp
import numpy as np

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


def lpcm_to_wav_bytes(pcm_data: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    """Упаковывает сырые LPCM байты в WAV-контейнер для корректного воспроизведения в браузере."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)  # 2 байта для PCM16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def sanitize_tts_text(text: str) -> str:
    """Очищает текст от markdown-форматирования, эмодзи и управляющих символов для TTS.
    - Убирает **жирный**, *курсив*, __подчёркивание__, `код`, заголовки #, ссылки [текст](url)
    - Убирает эмодзи (символы из категорий So/Sk и большинство эмодзи-блоков)
    - Схлопывает пробелы
    """
    if not text:
        return text
    t = text
    # Удаляем инлайн-код и маркдаун-обрамление
    t = re.sub(r"`+([^`]+)`+", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"__([^_]+)__", r"\1", t)
    t = re.sub(r"_([^_]+)_", r"\1", t)
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.MULTILINE)
    # Ссылки [текст](url) -> текст
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", t)
    # Убираем эмодзи и знаки из Symbol
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("So", "Sk"))
    # Удаляем управляющие
    t = "".join(ch for ch in t if ch.isprintable())
    # Схлопываем пробелы
    t = re.sub(r"\s+", " ", t).strip()
    return t


def trim_leading_silence(pcm_data: bytes, sample_rate: int, threshold: int = 300, max_trim_ms: int = 800) -> bytes:
    """Удаляет начальную тишину из PCM16 моно.
    threshold: амплитуда |sample| < threshold считается тишиной
    max_trim_ms: ограничение на максимальную длительность обрезки
    """
    if not pcm_data:
        return pcm_data
    try:
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        if samples.size == 0:
            return pcm_data
        max_trim_samples = int(sample_rate * max_trim_ms / 1000)
        max_trim_samples = min(max_trim_samples, samples.size)
        # Найти первый индекс за пределом тишины
        idx = 0
        while idx < max_trim_samples and abs(int(samples[idx])) < threshold:
            idx += 1
        if idx <= 0:
            return pcm_data
        return samples[idx:].astype(np.int16).tobytes()
    except Exception:
        return pcm_data


class SpeechKitASR:
    """Класс для работы с Yandex SpeechKit ASR (распознавание речи)."""
    
    def __init__(self, api_key: str, folder_id: str, endpoint: str = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"):
        self.api_key = api_key
        self.folder_id = folder_id
        self.asr_url = endpoint
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        """Инициализирует HTTP сессию."""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def recognize(self, audio_data: bytes) -> str:
        """Распознает речь из аудиоданных."""
        await self.initialize()
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "audio/x-pcm;bit=16;rate=16000"
        }
        
        params = {
            "folderId": self.folder_id,
            "lang": "ru-RU",
            "profanityFilter": "false",
            "format": "lpcm",
            "sampleRateHertz": 16000,
            "rawResults": "false"
        }
        
        url = f"{self.asr_url}?{urlencode(params)}"
        
        # Type checking to satisfy Pylance
        if self.session is None:
            logger.error("HTTP сессия не инициализирована")
            return ""
        
        try:
            async with self.session.post(url, data=audio_data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if "result" in result:
                        return result["result"]
                    else:
                        logger.error(f"ASR ошибка: {result}")
                        return ""
                else:
                    error_text = await response.text()
                    logger.error(f"ASR HTTP ошибка {response.status}: {error_text}")
                    return ""
        except Exception as e:
            logger.error(f"ASR ошибка: {e}")
            return ""
    
    async def cleanup(self):
        """Очищает ресурсы."""
        if self.session:
            await self.session.close()
            self.session = None


class SpeechKitStreamingASR:
    """Потоковое распознавание SpeechKit gRPC v3.

    Для работы должны быть сгенерированы protobuf-модули Yandex Cloud API:
    yandex.cloud.ai.stt.v3.stt_pb2 и stt_service_pb2_grpc.
    """

    def __init__(
        self,
        api_key: str,
        sample_rate: int = 16000,
        endpoint: str = "stt.api.cloud.yandex.net:443",
        language: str = "ru-RU",
        chunk_timeout: float = 5.0,
    ):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.endpoint = endpoint
        self.language = language
        self.chunk_timeout = chunk_timeout

        self._grpc = None
        self._stt_pb2 = None
        self._stt_service_pb2_grpc = None
        self._channel = None
        self._stub = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._audio_queue: queue.Queue[bytes | tuple[str, int] | None] = queue.Queue()
        self._event_queue: Optional[asyncio.Queue] = None
        self._worker: Optional[threading.Thread] = None
        self._started = False
        self._closed = False
        self._pending_final: Optional[str] = None

    async def initialize(self):
        """Инициализирует gRPC-сессию и фоновый поток чтения ответов."""
        if self._started:
            return

        try:
            import grpc
            import yandex.cloud.ai.stt.v3.stt_pb2 as stt_pb2
            import yandex.cloud.ai.stt.v3.stt_service_pb2_grpc as stt_service_pb2_grpc
        except ImportError as exc:
            raise RuntimeError(
                "Для потокового STT нужны grpcio/grpcio-tools и сгенерированные protobuf-модули "
                "Yandex Cloud API: yandex.cloud.ai.stt.v3.stt_pb2 и stt_service_pb2_grpc. "
                "Сгенерируйте их по инструкции из env.example или переключите SPEECHKIT_STT_MODE=batch."
            ) from exc

        self._grpc = grpc
        self._stt_pb2 = stt_pb2
        self._stt_service_pb2_grpc = stt_service_pb2_grpc
        self._loop = asyncio.get_running_loop()
        self._event_queue = asyncio.Queue()
        self._closed = False

        credentials = grpc.ssl_channel_credentials()
        self._channel = grpc.secure_channel(
            self.endpoint,
            credentials,
            options=[
                ("grpc.max_receive_message_length", 16 * 1024 * 1024),
                ("grpc.max_send_message_length", 16 * 1024 * 1024),
                ("grpc.enable_http_proxy", 0),
            ],
        )
        self._stub = stt_service_pb2_grpc.RecognizerStub(self._channel)

        self._worker = threading.Thread(target=self._run_stream, name="speechkit-stt-v3", daemon=True)
        self._worker.start()
        self._started = True

    def _build_streaming_options(self):
        stt_pb2 = self._stt_pb2
        return stt_pb2.StreamingOptions(
            recognition_model=stt_pb2.RecognitionModelOptions(
                audio_format=stt_pb2.AudioFormatOptions(
                    raw_audio=stt_pb2.RawAudio(
                        audio_encoding=stt_pb2.RawAudio.LINEAR16_PCM,
                        sample_rate_hertz=self.sample_rate,
                        audio_channel_count=1,
                    )
                ),
                text_normalization=stt_pb2.TextNormalizationOptions(
                    text_normalization=stt_pb2.TextNormalizationOptions.TEXT_NORMALIZATION_ENABLED,
                    profanity_filter=False,
                    literature_text=False,
                ),
                language_restriction=stt_pb2.LanguageRestrictionOptions(
                    restriction_type=stt_pb2.LanguageRestrictionOptions.WHITELIST,
                    language_code=[self.language],
                ),
                audio_processing_type=stt_pb2.RecognitionModelOptions.REAL_TIME,
            ),
            eou_classifier=stt_pb2.EouClassifierOptions(
                default_classifier=stt_pb2.DefaultEouClassifier(
                    type=stt_pb2.DefaultEouClassifier.HIGH,
                    max_pause_between_words_hint_ms=1000,
                )
            ),
        )

    def _request_iterator(self):
        stt_pb2 = self._stt_pb2
        yield stt_pb2.StreamingRequest(session_options=self._build_streaming_options())

        while not self._closed:
            item = self._audio_queue.get()
            if item is None:
                break
            if isinstance(item, tuple) and item[0] == "silence":
                yield stt_pb2.StreamingRequest(
                    silence_chunk=stt_pb2.SilenceChunk(duration_ms=item[1])
                )
            elif isinstance(item, tuple) and item[0] == "eou":
                yield stt_pb2.StreamingRequest(eou=stt_pb2.Eou())
            else:
                yield stt_pb2.StreamingRequest(chunk=stt_pb2.AudioChunk(data=item))

    def _put_event_threadsafe(self, event: dict) -> None:
        if self._loop and self._event_queue:
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)

    def _flush_pending_final(self) -> None:
        if self._pending_final:
            self._put_event_threadsafe({"type": "final", "text": self._pending_final})
            self._pending_final = None

    def _extract_texts(self, response, event_type: str) -> list[str]:
        if event_type == "partial":
            return [a.text for a in response.partial.alternatives]
        if event_type == "final":
            return [a.text for a in response.final.alternatives]
        if event_type == "final_refinement":
            return [a.text for a in response.final_refinement.normalized_text.alternatives]
        return []

    def _run_stream(self) -> None:
        try:
            responses = self._stub.RecognizeStreaming(
                self._request_iterator(),
                metadata=(("authorization", f"Api-Key {self.api_key}"),),
                timeout=305,
            )
            for response in responses:
                event_type = response.WhichOneof("Event")
                texts = self._extract_texts(response, event_type)
                text = texts[0].strip() if texts else ""

                if event_type == "partial":
                    self._flush_pending_final()
                    if text:
                        logger.info(f"Streaming STT partial: {text[:80]}")
                        self._put_event_threadsafe({"type": "partial", "text": text})
                elif event_type == "final":
                    logger.info(f"Streaming STT final: {text[:80]}")
                    self._pending_final = text
                    if text:
                        self._put_event_threadsafe({"type": "final", "text": text})
                elif event_type == "final_refinement":
                    self._pending_final = None
                    if text:
                        logger.info(f"Streaming STT final_refinement: {text[:80]}")
                        self._put_event_threadsafe({"type": "final", "text": text})
                elif event_type == "status_code":
                    logger.info(f"Streaming STT status: {response.status_code.code_type} {response.status_code.message}")
                elif event_type == "eou_update":
                    logger.info("Streaming STT eou_update")
                elif event_type and event_type not in ("status_code", "eou_update"):
                    self._flush_pending_final()
        except Exception as exc:
            logger.exception("Streaming STT worker error")
            self._put_event_threadsafe({"type": "error", "message": f"Streaming STT ошибка: {exc}"})
        finally:
            self._flush_pending_final()
            self._put_event_threadsafe({"type": "closed"})

    async def send_audio(self, audio_data: bytes) -> list[dict]:
        """Отправляет аудио в поток и возвращает накопившиеся события распознавания."""
        await self.initialize()
        if audio_data:
            self._audio_queue.put(audio_data)
        return await self.drain_events()

    async def finish_session(self, silence_ms: int = 900) -> list[dict]:
        """Завершает текущую фразу и возвращает финальные события распознавания."""
        await self.initialize()
        if silence_ms > 0:
            self._audio_queue.put(("silence", silence_ms))
        self._audio_queue.put(None)
        if self._worker and self._worker.is_alive():
            await asyncio.to_thread(self._worker.join, 5.0)
        events = await self.drain_events()
        self._started = False
        self._closed = True
        self._channel = None
        self._stub = None
        return events

    async def end_utterance(self, timeout: float = 1.2) -> list[dict]:
        """Завершает текущую фразу без закрытия gRPC-сессии."""
        await self.initialize()
        if not self._event_queue:
            return []

        self._audio_queue.put(("silence", 220))
        events: list[dict] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=max(0.1, deadline - loop.time()),
                )
            except asyncio.TimeoutError:
                logger.warning("Streaming STT: таймаут ожидания final после silence_chunk")
                break

            events.append(event)
            logger.info(f"Streaming STT событие после EOU: {event.get('type')} {event.get('text', '')[:80]}")
            if event.get("type") in ("final", "error", "closed"):
                break

        events.extend(await self.drain_events())
        return events

    async def drain_events(self) -> list[dict]:
        events: list[dict] = []
        if not self._event_queue:
            return events
        while True:
            try:
                events.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    async def reset_session(self) -> None:
        await self.cleanup()
        self._audio_queue = queue.Queue()
        self._pending_final = None
        await self.initialize()

    async def cleanup(self):
        self._closed = True
        if self._started:
            self._audio_queue.put(None)
        if self._channel:
            self._channel.close()
        self._started = False
        self._channel = None
        self._stub = None


class SpeechKitTTS:
    """Класс для работы с Yandex SpeechKit TTS (синтез речи)."""
    
    def __init__(self, api_key: str, folder_id: str, voice: str = "jane", endpoint: str = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"):
        self.api_key = api_key
        self.folder_id = folder_id
        self.voice = voice
        self.tts_url = endpoint
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        """Инициализирует HTTP сессию."""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def synthesize(self, text: str, sample_rate: int = 24000) -> bytes:
        """Синтезирует речь из текста."""
        await self.initialize()
        
        # Нормализация частоты: API v1 поддерживает 8000/16000/48000. Выберем 16000 по умолчанию
        if sample_rate not in (8000, 16000, 48000):
            sample_rate = 16000
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = {
            "text": text,
            "lang": "ru-RU",
            "voice": self.voice,
            "emotion": "neutral",
            "speed": "1.15",
            "format": "lpcm",
            "sampleRateHertz": str(sample_rate)
        }
        
        # Type checking to satisfy Pylance
        if self.session is None:
            logger.error("HTTP сессия не инициализирована")
            return b""
        
        try:
            async with self.session.post(self.tts_url, data=data, headers=headers) as response:
                if response.status == 200:
                    audio_data = await response.read()
                    return audio_data
                else:
                    error_text = await response.text()
                    logger.error(f"TTS HTTP ошибка {response.status}: {error_text}")
                    return b""
        except Exception as e:
            logger.error(f"TTS ошибка: {e}")
            return b""
    
    async def cleanup(self):
        """Очищает ресурсы."""
        if self.session:
            await self.session.close()
            self.session = None


class YandexLLM:
    """Класс для работы с Yandex LLM API."""
    
    def __init__(self, api_key: str, folder_id: str, endpoint: str = "https://llm.api.cloud.yandex.net/llm/v1/completion"):
        self.api_key = api_key
        self.folder_id = folder_id
        self.llm_url = endpoint
        self.session: Optional[aiohttp.ClientSession] = None
        self.history: list[dict[str, str]] = []
        self.max_history_messages = 12
    
    async def initialize(self):
        """Инициализирует HTTP сессию."""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def generate_response(self, prompt: str) -> str:
        """Генерирует ответ на основе текстового запроса."""
        await self.initialize()
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "general",
            "instruction_text": "Ты полезный голосовой ассистент.",
            "request_text": prompt,
            "folder_id": self.folder_id
        }
        
        # Type checking to satisfy Pylance
        if self.session is None:
            logger.error("HTTP сессия не инициализирована")
            return "Извините, произошла ошибка при обработке запроса."
        
        try:
            async with self.session.post(self.llm_url, json=data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if "result" in result:
                        answer = result["result"]["alternatives"][0]["message"]["text"]
                        self._remember(prompt, answer)
                        return answer
                    else:
                        logger.error(f"LLM ошибка: {result}")
                        return "Извините, я не могу ответить на этот вопрос."
                elif response.status == 404:
                    # Фолбэк на Foundation Models API
                    fm_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
                    fm_payload = {
                        "modelUri": f"gpt://{self.folder_id}/yandexgpt-lite",
                        "completionOptions": {
                            "stream": False,
                            "temperature": 0.3,
                            "maxTokens": 2000
                        },
                        "messages": self._build_messages(prompt)
                    }
                    async with self.session.post(fm_url, json=fm_payload, headers=headers) as fm_resp:
                        if fm_resp.status == 200:
                            fm_res = await fm_resp.json()
                            try:
                                answer = fm_res["result"]["alternatives"][0]["message"]["text"]
                                self._remember(prompt, answer)
                                return answer
                            except Exception:
                                logger.error(f"LLM FM ответ в неожиданном формате: {fm_res}")
                                return "Извините, я не могу ответить на этот вопрос."
                        else:
                            fm_text = await fm_resp.text()
                            logger.error(f"LLM FM HTTP ошибка {fm_resp.status}: {fm_text}")
                            return "Извините, произошла ошибка при обработке запроса."
                else:
                    error_text = await response.text()
                    logger.error(f"LLM HTTP ошибка {response.status}: {error_text}")
                    return "Извините, произошла ошибка при обработке запроса."
        except Exception as e:
            logger.error(f"LLM ошибка: {e}")
            return "Извините, произошла ошибка при обработке запроса."

    def _build_messages(self, prompt: str) -> list[dict[str, str]]:
        messages = [{"role": "system", "text": "Ты полезный голосовой ассистент. Отвечай кратко и по делу, сохраняя контекст разговора."}]
        messages.extend(self.history[-self.max_history_messages:])
        messages.append({"role": "user", "text": prompt})
        return messages

    def _remember(self, user_text: str, assistant_text: str) -> None:
        self.history.append({"role": "user", "text": user_text})
        self.history.append({"role": "assistant", "text": assistant_text})
        if len(self.history) > self.max_history_messages:
            self.history = self.history[-self.max_history_messages:]
    
    async def cleanup(self):
        """Очищает ресурсы."""
        if self.session:
            await self.session.close()
            self.session = None


class VoiceAgentCore:
    """Ядро голосового агента для работы с Yandex SpeechKit и LLM API."""
    
    def __init__(
        self,
        api_key: str,
        folder_id: str,
        stt_endpoint: str = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
        tts_endpoint: str = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
        llm_endpoint: str = "https://llm.api.cloud.yandex.net/llm/v1/completion",
        vector_store_id: str = "",
        voice: str = "jane",
        in_rate: int = 16000,
        out_rate: int = 24000,
        stt_mode: str = "batch",
        stt_grpc_endpoint: str = "stt.api.cloud.yandex.net:443"
    ):
        self.api_key = api_key
        self.folder_id = folder_id
        self.stt_endpoint = stt_endpoint
        self.tts_endpoint = tts_endpoint
        self.llm_endpoint = llm_endpoint
        self.vector_store_id = vector_store_id
        self.voice = voice
        self.in_rate = in_rate
        self.out_rate = out_rate
        self.stt_mode = (stt_mode or "batch").strip().lower()
        self.stt_grpc_endpoint = stt_grpc_endpoint
        
        # Валидация эндпоинтов окружения, чтобы избежать неподдерживаемых URL
        self._validate_endpoints()
        
        # Инициализируем компоненты
        self.asr = SpeechKitASR(api_key, folder_id, stt_endpoint)
        self.streaming_asr = SpeechKitStreamingASR(api_key, in_rate, stt_grpc_endpoint)
        self.tts = SpeechKitTTS(api_key, folder_id, voice, tts_endpoint)
        self.llm = YandexLLM(api_key, folder_id, llm_endpoint)
        
        self.response_queue: asyncio.Queue = asyncio.Queue()
        self.is_initialized = False
        self._response_lock = asyncio.Lock()
        self._last_processed_text: str = ""
        self._last_processed_ts: float = 0.0
        
        # Буферизация аудио для пакетной отправки в ASR
        self._audio_buffer = bytearray()
        self._last_asr_ts: float = 0.0
        self._asr_lock = asyncio.Lock()
        self._buffer_lock = asyncio.Lock()
        # Адаптивная VAD-логика
        self._baseline_rms: float | None = None
        self._calib_until_ts: float = 0.0  # до какого момента собираем фон
        self._speech_active: bool = False
        self._silence_since: float | None = None
        self._vad_silence_required: float = 0.22  # тишина для фиксации конца речи, сек
        self._streaming_voice_started: bool = False
        self._streaming_audio_started: bool = False
        self._pre_ms: int = 250
        self._post_ms: int = 200
        self._min_dur: float = 0.6
        self._max_dur: float = 5.0
        
    def _validate_endpoints(self) -> None:
        """Проверяет, что заданы поддерживаемые эндпоинты."""
        errors = []
        if self.stt_mode not in ("batch", "streaming"):
            errors.append(
                f"SPEECHKIT_STT_MODE должен быть batch или streaming, текущее значение: {self.stt_mode}"
            )
        # STT HTTP v1 нужен только для batch-режима.
        if self.stt_mode == "batch":
            if self.stt_endpoint.startswith("wss://") or "/stt/v3" in self.stt_endpoint:
                errors.append(
                    f"SPEECHKIT_STT_ENDPOINT='{self.stt_endpoint}' не поддерживается для batch. Используйте https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
                )
            if not self.stt_endpoint.startswith("http"):
                errors.append(
                    f"SPEECHKIT_STT_ENDPOINT должен начинаться с http/https, текущее значение: {self.stt_endpoint}"
                )
        if self.stt_mode == "streaming" and (not self.stt_grpc_endpoint or self.stt_grpc_endpoint.startswith("http")):
            errors.append(
                f"SPEECHKIT_STT_GRPC_ENDPOINT должен быть gRPC host:port, например stt.api.cloud.yandex.net:443"
            )
        # TTS: только HTTP v1
        if "/tts/v3" in self.tts_endpoint:
            errors.append(
                f"SPEECHKIT_TTS_ENDPOINT='{self.tts_endpoint}' не поддерживается. Используйте https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
            )
        if not self.tts_endpoint.startswith("http"):
            errors.append(
                f"SPEECHKIT_TTS_ENDPOINT должен начинаться с http/https, текущее значение: {self.tts_endpoint}"
            )
        # LLM: только llm/v1
        if "/foundationModels/" in self.llm_endpoint or "/v3" in self.llm_endpoint:
            errors.append(
                f"LLM_API_ENDPOINT='{self.llm_endpoint}' не поддерживается. Используйте https://llm.api.cloud.yandex.net/llm/v1/completion"
            )
        if not self.llm_endpoint.startswith("http"):
            errors.append(
                f"LLM_API_ENDPOINT должен начинаться с http/https, текущее значение: {self.llm_endpoint}"
            )
        if errors:
            raise ValueError("\n".join(errors))

    async def reset_vad(self) -> None:
        """Сбрасывает состояние VAD и инициирует калибровку фона на ближайшие 0.6с."""
        loop = asyncio.get_event_loop()
        now = loop.time()
        if self.stt_mode == "streaming" and self.is_initialized:
            await self.streaming_asr.reset_session()
        async with self._buffer_lock:
            self._audio_buffer.clear()
        self._baseline_rms = None
        self._calib_until_ts = now + 0.6
        self._speech_active = False
        self._silence_since = None
        self._streaming_voice_started = False
        self._streaming_audio_started = False

    async def initialize(self):
        """Инициализирует все компоненты."""
        if self.is_initialized:
            return
            
        # Инициализируем все сервисы
        if self.stt_mode == "streaming":
            await self.streaming_asr.initialize()
        else:
            await self.asr.initialize()
        await self.tts.initialize()
        await self.llm.initialize()
        
        self.is_initialized = True
        logger.info("Ядро голосового агента инициализировано")

    async def _process_recognized_text(self, text: str) -> dict:
        """Общий пайплайн после финального распознавания: LLM -> TTS."""
        if not text:
            return {"type": "error", "message": "Пустой текст распознавания"}
        if self._response_lock.locked():
            await self.response_queue.put({
                "type": "status",
                "status": "busy"
            })
            async with self._response_lock:
                pass

        async with self._response_lock:
            stop_words = {"стоп", "stop", "хватит", "молчи", "замолчи"}
            normalized_text = text.strip().lower().strip(" .,!?:;")
            normalized_text = re.sub(r"\s+", " ", normalized_text)
            now = asyncio.get_event_loop().time()
            if (
                normalized_text
                and normalized_text == self._last_processed_text
                and now - self._last_processed_ts < 8.0
            ):
                logger.info(f"Игнорирую повтор финального текста STT: {text[:80]}")
                return {"type": "duplicate_ignored", "text": text}
            self._last_processed_text = normalized_text
            self._last_processed_ts = now

            if normalized_text in stop_words:
                await self.response_queue.put({"type": "stop_audio"})
                await self.response_queue.put({"type": "response_done"})
                return {"type": "stopped"}

            await self.response_queue.put({
                "type": "transcription",
                "text": text
            })

            logger.info("Начало генерации ответа")
            response_text = await self.llm.generate_response(text)
            logger.info(f"Текст ответа: {response_text}")
            tts_text = sanitize_tts_text(response_text)

            await self.response_queue.put({
                "type": "text_delta",
                "text": response_text
            })

            logger.info("Начало синтеза речи")
            audio_response = await self.tts.synthesize(tts_text, self.out_rate)
            logger.info(f"Синтезировано аудио: {len(audio_response)} байт")

            if audio_response:
                trimmed = trim_leading_silence(audio_response, self.out_rate, threshold=300, max_trim_ms=800)
                wav_bytes = lpcm_to_wav_bytes(trimmed, self.out_rate, channels=1, sample_width=2)
                await self.response_queue.put({
                    "type": "audio_delta",
                    "audio": b64_encode(wav_bytes)
                })

            await self.response_queue.put({
                "type": "response_done"
            })

            return {
                "type": "response_done",
                "text": response_text,
                "audio": audio_response if audio_response else None
            }

    async def finish_audio(self) -> dict:
        """Фиксирует конец голосового ввода в streaming-режиме."""
        if not self.is_initialized:
            await self.initialize()
        if self.stt_mode != "streaming":
            return {"type": "ignored"}

        events = await self.streaming_asr.end_utterance()
        last_status: dict = {"type": "no_final"}
        for event in events:
            event_type = event.get("type")
            text = event.get("text", "")
            if event_type == "partial" and text:
                await self.response_queue.put({
                    "type": "partial_transcription",
                    "text": text
                })
                last_status = {"type": "partial", "text": text}
            elif event_type == "final" and text:
                logger.info(f"Финальный текст потокового STT: {text}")
                self._speech_active = False
                self._streaming_voice_started = False
                self._silence_since = None
                return await self._process_recognized_text(text)
            elif event_type == "error":
                await self.response_queue.put(event)
                return event

        self._speech_active = False
        self._streaming_voice_started = False
        self._silence_since = None
        return last_status
        
    async def process_audio(self, audio_data: bytes) -> dict:
        """Обрабатывает аудиоданные через пайплайн с буферизацией: ASR -> LLM -> TTS.
        Для API v1 отправляем не чаще, чем раз в ~0.7с и не менее ~0.7с аудио.
        """
        if not self.is_initialized:
            await self.initialize()

        if self.stt_mode == "streaming":
            try:
                samples = np.frombuffer(audio_data, dtype=np.int16)
                rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2))) if samples.size else 0.0
            except Exception:
                rms = 0.0

            loop = asyncio.get_event_loop()
            now = loop.time()

            if self._baseline_rms is None:
                async with self._buffer_lock:
                    self._audio_buffer.extend(audio_data)
                if now < self._calib_until_ts:
                    await self.streaming_asr.send_audio(audio_data)
                    return {"type": "calibrating"}
                try:
                    async with self._buffer_lock:
                        calib_snapshot = bytes(self._audio_buffer)
                        self._audio_buffer.clear()
                    s_all = np.frombuffer(calib_snapshot, dtype=np.int16)
                    if s_all.size:
                        frame = max(int(self.in_rate * 0.05), 1)
                        rms_values = [
                            float(np.sqrt(np.mean((s_all[i:i + frame].astype(np.float32) / 32768.0) ** 2)))
                            for i in range(0, s_all.size, frame)
                            if s_all[i:i + frame].size
                        ]
                        base = min(rms_values) if rms_values else 0.0
                    else:
                        base = 0.0
                except Exception:
                    base = 0.0
                self._baseline_rms = max(min(base, 0.006), 0.002)
                logger.info(f"Установлен уровень тишины для streaming STT (baseline RMS): {self._baseline_rms:.4f}")
                await self.streaming_asr.send_audio(audio_data)

            voice_threshold = max(self._baseline_rms * 1.6, self._baseline_rms + 0.0015, 0.004)
            voice_on = rms > voice_threshold
            if voice_on and not self._speech_active:
                self._speech_active = True
                self._streaming_voice_started = True
                self._silence_since = None
                await self.response_queue.put({"type": "speech_started"})

            events = await self.streaming_asr.send_audio(audio_data)
            self._streaming_audio_started = True
            last_status: dict = {"type": "streaming"}
            for event in events:
                event_type = event.get("type")
                text = event.get("text", "")
                if event_type == "partial" and text:
                    if not self._speech_active:
                        self._speech_active = True
                        self._streaming_voice_started = True
                        await self.response_queue.put({"type": "speech_started"})
                    await self.response_queue.put({
                        "type": "partial_transcription",
                        "text": text
                    })
                    last_status = {"type": "partial", "text": text}
                elif event_type == "final" and text:
                    logger.info(f"Финальный текст потокового STT: {text}")
                    return await self._process_recognized_text(text)
                elif event_type == "error":
                    await self.response_queue.put(event)
                    return event

            if voice_on:
                self._silence_since = None
            elif self._streaming_voice_started:
                if self._silence_since is None:
                    self._silence_since = now

            return last_status

        # Добавляем в буфер (под блокировкой буфера)
        async with self._buffer_lock:
            self._audio_buffer.extend(audio_data)

        text = None  # распознанный текст текущего сегмента, если будет
        pending_status = None  # статус для возврата, если распознавания не было

        # Оценка уровня сигнала по «хвосту» буфера
        try:
            async with self._buffer_lock:
                buf_snapshot = bytes(self._audio_buffer)
            # анализируем только последние ~0.4с
            bytes_per_sec = self.in_rate * 2  # mono PCM16
            tail_bytes = int(bytes_per_sec * 0.4)
            tail = buf_snapshot[-tail_bytes:] if len(buf_snapshot) > tail_bytes else buf_snapshot
            samples = np.frombuffer(tail, dtype=np.int16)
            rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2))) if samples.size else 0.0
        except Exception:
            rms = 0.0

        loop = asyncio.get_event_loop()
        now = loop.time()
        bytes_per_sec = self.in_rate * 2
        min_bytes = int(bytes_per_sec * self._min_dur)
        max_bytes = int(bytes_per_sec * self._max_dur)

        # Калибровка фона при старте/ресете
        if self._baseline_rms is None:
            if now < self._calib_until_ts:
                # накапливаем, ещё калибруемся
                return {"type": "calibrating"}
            # считаем baseline по накопленному
            try:
                async with self._buffer_lock:
                    calib_snapshot = bytes(self._audio_buffer)
                s_all = np.frombuffer(calib_snapshot, dtype=np.int16)
                base = float(np.sqrt(np.mean((s_all.astype(np.float32) / 32768.0) ** 2))) if s_all.size else 0.0
            except Exception:
                base = 0.0
            # страхуемся от нуля и задаём небольшой отступ
            self._baseline_rms = max(base, 0.003) + 0.004
            logger.info(f"Установлен уровень тишины (baseline RMS): {self._baseline_rms:.4f}")
            return {"type": "baseline_set"}

        # Если буфер меньше минимума — продолжаем копить
        async with self._buffer_lock:
            cur_len = len(self._audio_buffer)
        if cur_len < min_bytes:
            return {"type": "buffering"}
        # Исключаем конкурентные распознавания
        if self._asr_lock.locked():
            return {"type": "busy"}

        # VAD логика на основе baseline
        voice_on = rms > (self._baseline_rms + 0.003)
        if not self._speech_active and voice_on:
            self._speech_active = True
            self._silence_since = None
            pending_status = "speech_start"

        if self._speech_active:
            if voice_on:
                self._silence_since = None
                # если слишком длинно — форсируем сегмент
                if cur_len >= max_bytes:
                    async with self._asr_lock:
                        async with self._buffer_lock:
                            buf_snapshot = bytes(self._audio_buffer)
                            self._audio_buffer.clear()
                        self._speech_active = False
                        self._silence_since = None
                        self._last_asr_ts = now
                        # обрезка по амплитуде с прероллом/построллом
                        samples_all = np.frombuffer(buf_snapshot, dtype=np.int16)
                        if samples_all.size == 0:
                            return {"type": "silence"}
                        amp_thresh = max(int((self._baseline_rms + 0.003) * 32768), 300)
                        voiced = np.where(np.abs(samples_all) > amp_thresh)[0]
                        if voiced.size == 0:
                            return {"type": "silence"}
                        first_idx = int(voiced[0])
                        last_idx = int(voiced[-1])
                        pre_samp = int((self._pre_ms/1000.0) * self.in_rate)
                        post_samp = int((self._post_ms/1000.0) * self.in_rate)
                        start_idx = max(0, first_idx - pre_samp)
                        end_idx = min(samples_all.size, last_idx + post_samp)
                        chunk = samples_all[start_idx:end_idx].astype(np.int16).tobytes()
                        logger.info("Начало распознавания речи")
                        text = await self.asr.recognize(chunk)
                    logger.info(f"Распознанный текст: {text}")
                    # Продолжаем общий пайплайн ниже без раннего выхода
                else:
                    pending_status = "speaking"
            else:
                if self._silence_since is None:
                    self._silence_since = now
                if (now - self._silence_since) >= self._vad_silence_required:
                    # Конец фразы — сегментируем и распознаём
                    async with self._asr_lock:
                        async with self._buffer_lock:
                            buf_snapshot = bytes(self._audio_buffer)
                            self._audio_buffer.clear()
                        self._speech_active = False
                        self._silence_since = None
                        self._last_asr_ts = now
                        samples_all = np.frombuffer(buf_snapshot, dtype=np.int16)
                        if samples_all.size == 0:
                            return {"type": "silence"}
                        amp_thresh = max(int((self._baseline_rms + 0.003) * 32768), 300)
                        voiced = np.where(np.abs(samples_all) > amp_thresh)[0]
                        if voiced.size == 0:
                            return {"type": "silence"}
                        first_idx = int(voiced[0])
                        last_idx = int(voiced[-1])
                        pre_samp = int((self._pre_ms/1000.0) * self.in_rate)
                        post_samp = int((self._post_ms/1000.0) * self.in_rate)
                        start_idx = max(0, first_idx - pre_samp)
                        end_idx = min(samples_all.size, last_idx + post_samp)
                        chunk = samples_all[start_idx:end_idx].astype(np.int16).tobytes()
                        logger.info("Начало распознавания речи")
                        text = await self.asr.recognize(chunk)
                    logger.info(f"Распознанный текст: {text}")
                    # Продолжаем общий пайплайн ниже без раннего выхода
                else:
                    pending_status = "silence_wait"

        # Ещё не началась речь — ждём
        if text is None:
            return {"type": pending_status or "idle"}

        if not text:
            # Сохраняем буфер для повторной попытки позже, но ограничим размер
            async with self._buffer_lock:
                if len(self._audio_buffer) > max_bytes:
                    self._audio_buffer = bytearray(self._audio_buffer[-max_bytes:])
            # Небольшая пауза, чтобы не спамить API при ошибках/429
            await asyncio.sleep(0.8)
            return {"type": "error", "message": "Не удалось распознать речь"}
        
        # Успех распознавания — очищаем буфер
        async with self._buffer_lock:
            self._audio_buffer.clear()
        
        # Отправляем распознанный текст
        await self.response_queue.put({
            "type": "transcription",
            "text": text
        })
        
        # 2. Генерация ответа (LLM)
        logger.info("Начало генерации ответа")
        response_text = await self.llm.generate_response(text)
        logger.info(f"Текст ответа: {response_text}")
        # Очистим текст от форматирования/эмодзи перед синтезом, чтобы не проговаривать служебные символы
        tts_text = sanitize_tts_text(response_text)
        
        # Отправляем текст ответа
        await self.response_queue.put({
            "type": "text_delta",
            "text": response_text
        })
        
        # 3. Синтез речи (TTS)
        logger.info("Начало синтеза речи")
        audio_response = await self.tts.synthesize(tts_text, self.out_rate)
        logger.info(f"Синтезировано аудио: {len(audio_response)} байт")
        
        if audio_response:
            # Уберём стартовую тишину для ускорения начала воспроизведения
            trimmed = trim_leading_silence(audio_response, self.out_rate, threshold=300, max_trim_ms=800)
            # Оборачиваем LPCM в WAV, чтобы браузер гарантированно декодировал через decodeAudioData
            wav_bytes = lpcm_to_wav_bytes(trimmed, self.out_rate, channels=1, sample_width=2)
            await self.response_queue.put({
                "type": "audio_delta",
                "audio": b64_encode(wav_bytes)
            })
        
        # Завершаем обработку
        await self.response_queue.put({
            "type": "response_done"
        })
        
        return {
            "type": "response_done",
            "text": response_text,
            "audio": audio_response if audio_response else None
        }
    
    async def process_text(self, text: str) -> dict:
        """Обрабатывает текстовый запрос через пайплайн: LLM -> TTS."""
        if not self.is_initialized:
            await self.initialize()
        
        # Отправляем текст запроса
        await self.response_queue.put({
            "type": "transcription",
            "text": text
        })
        
        # 1. Генерация ответа (LLM)
        logger.info("Начало генерации ответа")
        response_text = await self.llm.generate_response(text)
        logger.info(f"Текст ответа: {response_text}")
        
        # Отправляем текст ответа
        await self.response_queue.put({
            "type": "text_delta",
            "text": response_text
        })
        
        # 2. Синтез речи (TTS)
        logger.info("Начало синтеза речи")
        audio_response = await self.tts.synthesize(response_text, self.out_rate)
        logger.info(f"Синтезировано аудио: {len(audio_response)} байт")
        
        if audio_response:
            wav_bytes = lpcm_to_wav_bytes(audio_response, self.out_rate, channels=1, sample_width=2)
            await self.response_queue.put({
                "type": "audio_delta",
                "audio": b64_encode(wav_bytes)
            })
        
        # Завершаем обработку
        await self.response_queue.put({
            "type": "response_done"
        })
        
        return {
            "type": "response_done",
            "text": response_text,
            "audio": audio_response if audio_response else None
        }
    
    async def get_responses(self) -> AsyncGenerator[dict, None]:
        """Генератор для получения ответов от агента."""
        while True:
            try:
                response = await self.response_queue.get()
                yield response
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка получения ответа: {e}")
                break
    
    async def cleanup(self):
        """Очищает ресурсы."""
        await self.asr.cleanup()
        await self.streaming_asr.cleanup()
        await self.tts.cleanup()
        await self.llm.cleanup()
        
        self.is_initialized = False
        logger.info("Очистка ресурсов ядра голосового агента завершена")
