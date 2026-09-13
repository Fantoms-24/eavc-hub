from __future__ import annotations

from typing import Any
import numpy as np
try:
    import torch
except Exception:  # pragma: no cover
    torch = None

from web_portal.lib.ml.model import GraphEventNet, load_checkpoint, ensure_torch
from web_portal.lib.ml.features import FEATURE_ORDER


def predict_probabilities(artifact_path: str, feature_vector: list[float]) -> dict[str, Any]:
    ensure_torch()
    if torch is None:
        raise RuntimeError(
            "PyTorch не установлен. Установите зависимости из requirements.txt для ML."
        )
    ckpt = load_checkpoint(artifact_path)
    labels = [str(x) for x in (ckpt.get("labels") or [])]
    if not labels:
        raise RuntimeError("Модель не содержит labels")
    mean = np.array(ckpt.get("mean") or [0.0] * len(FEATURE_ORDER), dtype=np.float32)
    std = np.array(ckpt.get("std") or [1.0] * len(FEATURE_ORDER), dtype=np.float32)
    vec = np.array(feature_vector, dtype=np.float32)
    std = np.where(std < 1e-6, 1.0, std)
    x = (vec - mean) / std

    model = GraphEventNet(input_dim=len(FEATURE_ORDER), num_classes=len(labels))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(x, dtype=torch.float32).unsqueeze(0))
        probs = torch.softmax(logits, dim=1).squeeze(0).cpu().numpy().tolist()
    pairs = [{"label": labels[i], "probability": float(probs[i])} for i in range(len(labels))]
    pairs.sort(key=lambda x: x["probability"], reverse=True)
    return {"labels": labels, "probabilities": pairs, "top": pairs[0] if pairs else None}

