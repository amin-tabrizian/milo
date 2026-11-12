"""Local speech: whisper.cpp server for STT. Kokoro (neural, on this Mac) or macOS `say` for TTS."""

import asyncio
import logging
import re
import shutil
import tempfile
import threading
from pathlib import Path

import httpx

log = logging.getLogger("speech")


class Whisper:
    def __init__(self, model: Path, port: int = 8178):
        self.model = model
        self.port = port
        self.proc: asyncio.subprocess.Process | None = None
        self.url = f"http://127.0.0.1:{port}"

    async def start(self) -> None:
        binary = shutil.which("whisper-server")
        if not binary:
            raise RuntimeError("whisper-server not found; run: brew install whisper-cpp")
        if not self.model.exists():
            raise RuntimeError(f"whisper model missing: {self.model}")
        self.proc = await asyncio.create_subprocess_exec(
            binary, "-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port), "--convert",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        async with httpx.AsyncClient() as client:
            for _ in range(120):
                try:
                    await client.get(self.url, timeout=1)
                    log.info("whisper-server ready on %s", self.url)
                    return
                except httpx.HTTPError:
                    await asyncio.sleep(0.5)
        raise RuntimeError("whisper-server did not start")

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            await self.proc.wait()

    async def transcribe(self, audio: bytes, filename: str) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.url}/inference",
                files={"file": (filename, audio)},
                data={"response_format": "json", "temperature": "0.0"},
            )
            r.raise_for_status()
            text = r.json().get("text", "")
        text = re.sub(r"\[(BLANK_AUDIO|MUSIC|NOISE)[^\]]*\]", "", text, flags=re.I)
        return " ".join(text.split())


def speakable(markdown: str, limit: int = 900) -> str:
    """Turn a markdown reply into text that sounds natural when read aloud."""
    t = re.sub(r"```.*?```", " (code omitted) ", markdown, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\|.*\|\s*$", "", t, flags=re.M)
    t = re.sub(r"[*_~>#|]", "", t)
    t = " ".join(t.split())
    if len(t) > limit:
        cut = t[:limit]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        t = (cut[: end + 1] if end > limit // 2 else cut) + " The rest is on screen."
    return t


def split_speech(text: str, size: int = 220) -> list[str]:
    """Cut speakable text into parts of whole sentences, so the first part can play while the next is made.
    The first part is short, so speech starts fast."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    parts: list[str] = []
    for s in sentences:
        limit = size // 2 if len(parts) <= 1 else size
        if parts and len(parts[-1]) + len(s) < limit:
            parts[-1] += " " + s
        else:
            parts.append(s)
    return parts


KOKORO_ACCENTS = {"a": "US", "b": "UK"}


class NeuralVoice:
    """Kokoro-82M through onnxruntime. Natural voices, about 5x faster than real time on Apple silicon."""

    def __init__(self, model: Path, voices: Path):
        self.model, self.voices_file = model, voices
        self.engine = None
        self.lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.model.exists() and self.voices_file.exists()

    def _engine(self):
        if self.engine is None:
            from kokoro_onnx import Kokoro
            self.engine = Kokoro(str(self.model), str(self.voices_file))
        return self.engine

    def voices(self) -> list[dict]:
        if not self.available:
            return []
        out = []
        for v in sorted(self._engine().get_voices()):
            accent = KOKORO_ACCENTS.get(v[0])
            if accent and v[1] in "fm" and "_" in v:
                gender = "male" if v[1] == "m" else "female"
                out.append({"name": v, "label": f"{v.split('_', 1)[1].title()} (natural, {accent} {gender})",
                            "natural": True, "male": v[1] == "m"})
        return sorted(out, key=lambda x: (not x["male"], x["label"]))

    def is_voice(self, voice: str) -> bool:
        return bool(re.fullmatch(r"[ab][fm]_[a-z]+", voice)) and self.available

    def _render(self, text: str, voice: str, speed: float, out: Path) -> None:
        import soundfile
        with self.lock:   # one at a time: parallel runs only slow each other down
            samples, rate = self._engine().create(text, voice=voice, speed=speed, lang="en-gb" if voice[0] == "b" else "en-us")
        soundfile.write(out, samples, rate, subtype="PCM_16")

    async def synthesize(self, text: str, voice: str, rate: int) -> bytes:
        """Render speech to AAC (.m4a). rate is in words per minute like `say`; 190 is normal speed."""
        speed = max(0.6, min(1.6, rate / 190))
        with tempfile.TemporaryDirectory() as tmp:
            wav, m4a = Path(tmp) / "speech.wav", Path(tmp) / "speech.m4a"
            await asyncio.to_thread(self._render, text, voice, speed, wav)
            proc = await asyncio.create_subprocess_exec("afconvert", "-f", "m4af", "-d", "aac", str(wav), str(m4a),
                                                        stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"afconvert failed: {err.decode().strip()}")
            return m4a.read_bytes()


async def synthesize(text: str, voice: str, rate: int) -> bytes:
    """Render speech to AAC (.m4a), which iOS Safari plays natively."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "speech.m4a"
        src = Path(tmp) / "speech.txt"
        src.write_text(text)
        proc = await asyncio.create_subprocess_exec(
            "say", "-v", voice, "-r", str(rate), "-f", str(src),
            "-o", str(out), "--file-format=m4af", "--data-format=aac",
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"say failed: {err.decode().strip()}")
        return out.read_bytes()
