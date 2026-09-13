from __future__ import annotations

from pathlib import Path
from typing import Any

from web_portal.lib.asr.model import (
    build_operator_blank,
    estimate_confidence,
    operator_line_with_id,
    operator_ru_formatter,
)
from web_portal.lib.asr.runtime import asr_runtime, resolve_whisper_short_name

_ASR_LANG_TRY = ("uk", "ru")

# Смещает распознавание к типичным фразам радиосвязи без дообучения.
_RADIO_ASR_INITIAL_PROMPT = (
    "Радіоперехоплення, радіозв'язок. На зв'язку. Прийом. Зрозумів. Вихід. "
    "Повтори. Як чутно. Працюю. Чекаю. Відбій. Викликаю. Відповідай. "
    "Радиоперехват, радиосвязь. На связи. Приём. Понял. Выход. Повтори. "
    "Как слышно. Работаю. Жду. Отбой. Вызываю. Ответь. Сектор. Позиция. "
    "Квартал. Частота. Готов. Есть. Принял. Передаю. Слушаю. Вызов."
)


def _segment_is_noise(seg: dict[str, Any]) -> bool:
    return bool(seg.get("has_key")) and not bool(seg.get("has_message"))


def _transcribe_whisper(
    model: Any,
    audio_file: str,
    *,
    prev_text: str = "",
) -> dict[str, Any]:
    prompt = _RADIO_ASR_INITIAL_PROMPT
    tail = str(prev_text or "").strip()
    if tail:
        prompt = f"{_RADIO_ASR_INITIAL_PROMPT} {tail[-220:]}"
    last_exc: Exception | None = None
    for lang in _ASR_LANG_TRY:
        try:
            res = model.transcribe(
                audio_file,
                language=lang,
                task="transcribe",
                fp16=False,
                verbose=False,
                condition_on_previous_text=False,
                temperature=0.0,
                initial_prompt=prompt,
            )
            text = str((res or {}).get("text") or "").strip()
            if text:
                return res if isinstance(res, dict) else {"text": text, "segments": []}
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    return {"text": "", "segments": []}


def _segments_from_whisper(raw: dict[str, Any]) -> list[dict[str, float | str]]:
    out: list[dict[str, float | str]] = []
    for s in raw.get("chunks") or raw.get("segments") or []:
        seg_txt = str(s.get("text") or "").strip()
        ts = s.get("timestamp")
        start = 0.0
        end = 0.0
        if isinstance(ts, (list, tuple)) and len(ts) == 2:
            start = float(ts[0] or 0.0)
            end = float(ts[1] or 0.0)
        else:
            start = float(s.get("start") or 0.0)
            end = float(s.get("end") or 0.0)
        out.append({"start": start, "end": end, "text": seg_txt})
    return out


def transcribe_audio_to_operator_ru(
    *,
    audio_file: str,
    model_name: str,
    model_version: str = "",
    correspondent_id: str = "",
) -> dict[str, Any]:
    fpath = Path(audio_file)
    if not fpath.exists() or not fpath.is_file():
        raise FileNotFoundError(f"Аудиофайл не найден: {audio_file}")
    if fpath.suffix.lower() != ".wav":
        raise ValueError("Поддерживается только .wav")

    short = resolve_whisper_short_name(model_name)

    def _work() -> dict[str, Any]:
        model = asr_runtime.get_model(short)
        raw_result = _transcribe_whisper(model, str(fpath))
        text = str((raw_result or {}).get("text") or "").strip()
        line = operator_line_with_id(text, correspondent_id) if correspondent_id else operator_ru_formatter(text)
        confidence = estimate_confidence(raw_result)
        return {
            "ua_text": text,
            "ru_text": text,
            "formatted_text": line,
            "segments": _segments_from_whisper(raw_result or {}),
            "confidence": confidence,
            "model_version": str(model_version or ""),
            "model_name": short,
        }

    return asr_runtime.run(_work)


def transcribe_track_segments_to_operator_blank(
    *,
    segments: list[dict[str, Any]],
    resolve_audio_path: Any,
    model_name: str,
    model_version: str = "",
    recorded_at: str = "",
    frequency: str = "",
    group_code: str = "",
) -> dict[str, Any]:
    if not segments:
        raise ValueError("segments обязателен")

    short = resolve_whisper_short_name(model_name)

    def _work() -> dict[str, Any]:
        model = asr_runtime.get_model(short)
        operator_lines: list[str] = []
        seg_out: list[dict[str, Any]] = []
        confidences: list[float] = []
        header_time = str(recorded_at or "").strip()
        prev_seg_text = ""
        for idx, seg in enumerate(segments):
            file_rel = str(seg.get("file_rel") or "").strip()
            if not file_rel:
                continue
            cid = str(seg.get("correspondent_id") or "").strip()
            if _segment_is_noise(seg):
                seg_out.append(
                    {
                        "index": idx,
                        "file_key": str(seg.get("file_key") or ""),
                        "file_rel": file_rel,
                        "correspondent_id": cid,
                        "text": "",
                        "formatted_line": "",
                        "confidence": 0.0,
                        "segments": [],
                        "skipped": "noise",
                    }
                )
                continue
            audio_path = str(resolve_audio_path(file_rel))
            if not audio_path or not Path(audio_path).is_file():
                continue
            raw = _transcribe_whisper(model, audio_path, prev_text=prev_seg_text)
            text = str((raw or {}).get("text") or "").strip()
            if text:
                prev_seg_text = text
            if not header_time:
                header_time = str(seg.get("recorded_at") or "").strip()
            line = operator_line_with_id(text, cid)
            if line:
                operator_lines.append(line)
            conf = estimate_confidence(raw)
            confidences.append(conf)
            seg_out.append(
                {
                    "index": idx,
                    "file_key": str(seg.get("file_key") or ""),
                    "file_rel": file_rel,
                    "correspondent_id": cid,
                    "text": text,
                    "formatted_line": line,
                    "confidence": conf,
                    "segments": _segments_from_whisper(raw or {}),
                }
            )
        formatted = build_operator_blank(
            recorded_at=header_time,
            segment_lines=operator_lines,
        )
        avg_conf = float(sum(confidences) / len(confidences)) if confidences else 0.0
        return {
            "ua_text": "\n".join(operator_lines),
            "ru_text": "\n".join(operator_lines),
            "formatted_text": formatted,
            "segments": seg_out,
            "confidence": avg_conf,
            "model_version": str(model_version or ""),
            "model_name": short,
            "frequency": str(frequency or ""),
            "group_code": str(group_code or ""),
            "recorded_at": header_time,
        }

    return asr_runtime.run(_work, timeout_sec=3600.0)


def make_group_transcript_key(group_key: str) -> str:
    gk = str(group_key or "").strip()
    if not gk:
        raise ValueError("group_key обязателен")
    return f"asr-group:{gk}"
