"""Word-level transcription with faster-whisper (runs on CPU)."""
import json
from pathlib import Path


def transcribe(video: Path, model_name: str, language: str | None, cache: Path) -> list[dict]:
    """Return a list of segments: {start, end, text, words:[{start,end,word}]}."""
    if cache.exists():
        return json.loads(cache.read_text())

    from faster_whisper import WhisperModel

    import os
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=os.cpu_count() or 4)
    segments, info = model.transcribe(
        str(video), word_timestamps=True, vad_filter=True, language=language
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


def all_words(segments: list[dict]) -> list[dict]:
    return [w for s in segments for w in s["words"]]
