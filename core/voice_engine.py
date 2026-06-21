"""
voice_engine.py -- Voice Input/Output for the Himalayan GIS Agent System.

Uses edge-tts for text-to-speech, pygame for playback,
faster-whisper for speech-to-text, and sounddevice for microphone capture.
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

# -- Voice map ----------------------------------------------------------------

VOICE_MAP = {
    "hindi_girl":   "hi-IN-SwaraNeural",
    "english_girl": "en-US-AriaNeural",
    "jarvis":       "en-US-GuyNeural",
}

_pygame_initialised = False


def _init_pygame():
    """Lazily initialise pygame.mixer once."""
    global _pygame_initialised
    if _pygame_initialised:
        return
    try:
        import pygame
        pygame.mixer.init()
        _pygame_initialised = True
    except Exception as exc:
        print(f"  [WARN] pygame.mixer init failed: {exc}")


# -- Text-to-Speech -----------------------------------------------------------

def speak(text: str, voice_key: str = "english_girl") -> None:
    """Convert *text* to speech via edge-tts and play through speakers."""
    tmp_path = None
    try:
        import edge_tts
        import pygame

        _init_pygame()

        voice = VOICE_MAP.get(voice_key, VOICE_MAP["english_girl"])

        # Create temp mp3
        fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="gis_tts_")
        os.close(fd)

        # edge-tts is async -- run in event loop
        async def _generate():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(tmp_path)

        asyncio.run(_generate())

        # Play with pygame
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)

    except ImportError as exc:
        print(f"  [WARN] Missing package for TTS: {exc}")
        print(f"  [TEXT] (Would have said: {text[:80]}...)")
    except Exception as exc:
        print(f"  [WARN] TTS error: {exc}")
        print(f"  [TEXT] (Would have said: {text[:80]}...)")
    finally:
        # Clean up temp file
        if tmp_path:
            try:
                # Unload from pygame first
                try:
                    import pygame
                    pygame.mixer.music.unload()
                except Exception:
                    pass
                os.unlink(tmp_path)
            except Exception:
                pass


# -- Speech-to-Text -----------------------------------------------------------

def listen(duration: int = 5) -> str:
    """Record *duration* seconds of audio and transcribe to text."""
    tmp_path = None
    try:
        import numpy as np
        import sounddevice as sd
        import wave

        print(f"  [MIC] Listening for {duration} seconds ...")
        sample_rate = 16000
        audio = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        print("  [MIC] Processing ...")

        # Save to temp WAV
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="gis_stt_")
        os.close(fd)
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())

        # Transcribe with faster-whisper
        from faster_whisper import WhisperModel

        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, info = model.transcribe(tmp_path)
        text = " ".join(seg.text for seg in segments).strip()
        print(f"  [MIC] Detected language: {info.language} (prob {info.language_probability:.2f})")
        return text

    except ImportError as exc:
        print(f"  [WARN] Missing package for STT: {exc}")
        return ""
    except Exception as exc:
        print(f"  [WARN] Microphone/STT error: {exc}")
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
