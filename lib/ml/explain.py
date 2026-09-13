from __future__ import annotations

from typing import Any

from web_portal.lib.ml.features import FEATURE_ORDER


def explain_feature_contributions(
    feature_values: dict[str, float],
    probabilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Простая и прозрачная расшифровка: сигналы относительно порогов.
    feats = {k: float(feature_values.get(k, 0.0)) for k in FEATURE_ORDER}
    rules = [
        ("new_ratio", 0.35, "всплеск новых ID"),
        ("gone_ratio", 0.35, "резкий уход ID"),
        ("hub_concentration", 0.45, "концентрация вокруг хаба"),
        ("cross_group_ratio", 0.45, "рост межгрупповой связности"),
        ("recent_edge_ratio", 0.60, "много свежих связей"),
        ("density", 0.12, "аномально высокая плотность графа"),
    ]
    out: list[dict[str, Any]] = []
    for name, threshold, text in rules:
        val = float(feats.get(name, 0.0))
        score = max(0.0, (val - threshold) / max(1e-6, threshold))
        if score > 0:
            out.append({"feature": name, "reason": text, "value": round(val, 6), "score": round(score, 4)})
    out.sort(key=lambda x: x["score"], reverse=True)
    if not out:
        out = [{"feature": "baseline", "reason": "выраженных аномалий не найдено", "value": 0.0, "score": 0.0}]
    top_label = probabilities[0]["label"] if probabilities else "unknown"
    return [
        {"type": "class", "label": top_label},
        *out[:6],
    ]


def explain_hotspots(
    top_units: list[dict[str, Any]],
    top_groups: list[dict[str, Any]],
    top_ids: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total_unit = sum(int(x.get("count") or 0) for x in top_units) or 1
    total_group = sum(int(x.get("count") or 0) for x in top_groups) or 1
    total_id = sum(float(x.get("score") or 0) for x in top_ids) or 1.0
    for x in top_units[:4]:
        cnt = int(x.get("count") or 0)
        out.append({"kind": "unit", "name": str(x.get("name") or "—"), "contribution": round(100.0 * cnt / total_unit, 2)})
    for x in top_groups[:4]:
        cnt = int(x.get("count") or 0)
        out.append({"kind": "group", "name": str(x.get("name") or "—"), "contribution": round(100.0 * cnt / total_group, 2)})
    for x in top_ids[:5]:
        sc = float(x.get("score") or 0.0)
        out.append({"kind": "id", "name": str(x.get("id") or "—"), "contribution": round(100.0 * sc / total_id, 2)})
    out.sort(key=lambda x: float(x.get("contribution") or 0.0), reverse=True)
    return out[:10]

