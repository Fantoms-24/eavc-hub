"""POST /api/intercepts/ai/proofread — AI и словарная проверка бланка."""

from __future__ import annotations

from typing import Any
import json
import re

from web_portal.lib.ai_client import generate_ai_text
from web_portal.lib.ai_prompts import AI_SYSTEM_PROMPT, build_intercept_proofread_prompt


def _derive_proofread_issue(source: str, corrected_text: str) -> list[dict[str, str]]:
    if not source or not corrected_text or source == corrected_text:
        return []
    left = 0
    while (
        left < len(source)
        and left < len(corrected_text)
        and source[left] == corrected_text[left]
    ):
        left += 1
    right_source = len(source) - 1
    right_corrected = len(corrected_text) - 1
    while (
        right_source >= left
        and right_corrected >= left
        and source[right_source] == corrected_text[right_corrected]
    ):
        right_source -= 1
        right_corrected -= 1
    while left > 0 and re.match(r"[\w\-]", source[left - 1], re.U):
        left -= 1
    while right_source + 1 < len(source) and re.match(
        r"[\w\-]", source[right_source + 1], re.U
    ):
        right_source += 1
    while right_corrected + 1 < len(corrected_text) and re.match(
        r"[\w\-]", corrected_text[right_corrected + 1], re.U
    ):
        right_corrected += 1
    original = source[left : right_source + 1].strip()
    fixed = corrected_text[left : right_corrected + 1].strip()
    if not original or not fixed or original == fixed:
        return []
    return [
        {
            "original": original,
            "corrected": fixed,
            "reason": "AI предложил точечное исправление.",
        }
    ]


def _deterministic_proofread(source: str) -> tuple[str, list[dict[str, str]]]:
    typo_map = {
        "асколок": "осколок",
        "асколка": "осколка",
        "асколком": "осколком",
        "асколки": "осколки",
        "асколков": "осколков",
        "раненыйй": "раненый",
        "раненныйй": "раненный",
        "эвакуацыя": "эвакуация",
        "евакуация": "эвакуация",
        "боекомплекту": "боекомплекта",
        "слапай": "слушай",
        "слпашай": "слушай",
        "слушаи": "слушай",
        "слушаы": "слушай",
        "слушпй": "слушай",
        "спашай": "слушай",
    }
    issues_local: list[dict[str, str]] = []

    def repl(match: re.Match) -> str:
        word = match.group(0)
        fixed = typo_map.get(word.lower())
        if not fixed:
            return word
        if word[:1].isupper():
            fixed = fixed[:1].upper() + fixed[1:]
        issues_local.append(
            {
                "original": word,
                "corrected": fixed,
                "reason": "Словарная проверка очевидной опечатки.",
            }
        )
        return fixed

    corrected_local = re.sub(
        r"(?iu)\b(" + "|".join(re.escape(k) for k in typo_map.keys()) + r")\b",
        repl,
        source,
    )
    return corrected_local, issues_local[:20]


def execute_intercepts_ai_proofread(*, text: str) -> dict[str, Any]:
    deterministic_corrected, deterministic_issues = _deterministic_proofread(text)

    try:
        ai = generate_ai_text(
            system_prompt=AI_SYSTEM_PROMPT,
            user_prompt=build_intercept_proofread_prompt(text=text),
            temperature=0.0,
            max_tokens=1200,
        )
        raw = str(ai.get("text") or "").strip()
        raw_json = raw
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            raw_json = m.group(0)
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            payload = {}
        corrected = str(payload.get("corrected_text") or text)
        issues_raw = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        issues: list[dict[str, str]] = []
        for issue in issues_raw[:50]:
            if not isinstance(issue, dict):
                continue
            original = str(issue.get("original") or "").strip()
            corrected_word = str(issue.get("corrected") or "").strip()
            if not original or not corrected_word or original == corrected_word:
                continue
            issues.append(
                {
                    "original": original,
                    "corrected": corrected_word,
                    "reason": str(issue.get("reason") or "").strip()[:300],
                }
            )
        if corrected != text and not issues:
            issues = _derive_proofread_issue(text, corrected)
        if deterministic_issues and (corrected == text or not issues):
            corrected = deterministic_corrected
            issues = deterministic_issues
        return {
            "ok": True,
            "corrected_text": corrected,
            "issues": issues,
            "model": ai.get("model") or "",
            "changed": corrected != text,
        }
    except Exception as e:
        if deterministic_issues:
            return {
                "ok": True,
                "corrected_text": deterministic_corrected,
                "issues": deterministic_issues,
                "model": "",
                "changed": deterministic_corrected != text,
                "ai_error": str(e),
            }
        return {
            "ok": True,
            "corrected_text": text,
            "issues": [],
            "model": "",
            "changed": False,
            "ai_error": str(e),
        }
