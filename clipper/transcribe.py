"""Word-level transcription with faster-whisper (runs on CPU)."""
import json
import os
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def load_audio(video: Path) -> np.ndarray:
    """Decode the audio track to 16 kHz mono float32 with ffmpeg.
    (faster-whisper's own decoder breaks with newer PyAV releases.)"""
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    if not has_audio:  # muted / silent recording: nothing to transcribe
        print("[transcribe] no audio track in this part")
        return np.zeros(0, np.float32)
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def transcribe(video: Path, model_name: str, language: str | None, cache: Path) -> list[dict]:
    """Return a list of segments: {start, end, text, words:[{start,end,word}]}."""
    if cache.exists():
        return json.loads(cache.read_text())

    from faster_whisper import WhisperModel

    audio = load_audio(video)
    if audio.size == 0:
        return []
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=os.cpu_count() or 4)
    segments, info = model.transcribe(
        audio, word_timestamps=True, vad_filter=True, language=language
    )
    out = []
    for s in segments:
        words = [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                 for w in (s.words or []) if w.word.strip()]
        if words:
            out.append({"start": round(s.start, 2), "end": round(s.end, 2),
                        "text": s.text.strip(), "words": words})
    print(f"[transcribe] {len(out)} segments, language={info.language}")
    cache.write_text(json.dumps(out))
    return out


def add_energy(video: Path, segments: list[dict]) -> list[dict]:
    """Score each segment 0-10 by how loud it gets compared with the rest of the
    video (yelling, laughing, hype). Stored as segment["energy"].
    Returns marker lines for very loud stretches with NO talking (crash, explosion,
    gunfight, chase): gameplay moments the transcript alone would never show."""
    audio = load_audio(video)
    win = SAMPLE_RATE // 2  # 0.5 s windows
    n = len(audio) // win
    if n < 4:
        return []
    rms = np.sqrt(np.mean(audio[: n * win].reshape(n, win) ** 2, axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    ranks = np.argsort(np.argsort(db)) / max(n - 1, 1)  # 0..1 percentile per window
    for s in segments:
        a, b = int(s["start"] * 2), max(int(s["end"] * 2), int(s["start"] * 2) + 1)
        seg = ranks[a:b]
        if len(seg):
            s["energy"] = int(round(float(np.max(seg)) * 10))

    # loud gameplay in the gaps between speech
    talking = np.zeros(n, bool)
    for s in segments:
        talking[int(s["start"] * 2):int(s["end"] * 2) + 1] = True
    loud = (ranks >= 0.97) & ~talking
    markers, i = [], 0
    while i < n:
        if loud[i]:
            j = i
            while j + 1 < n and (loud[j + 1] or (j + 2 < n and loud[j + 2])):
                j += 1
            if j - i >= 3:  # at least ~2 s of it
                markers.append({"start": round(i / 2, 2), "end": round((j + 1) / 2, 2),
                                "text": "[no talking: very loud game moment]",
                                "energy": int(round(float(np.max(ranks[i:j + 1])) * 10)),
                                "words": [], "marker": True})
            i = j + 1
        else:
            i += 1
    return markers[:40]


def all_words(segments: list[dict]) -> list[dict]:
    return [w for s in segments for w in s["words"]]
