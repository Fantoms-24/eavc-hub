from __future__ import annotations

from typing import Any

try:
    import torch
    import torch.nn as nn
except Exception:  # pragma: no cover
    torch = None
    nn = None


# Без PyTorch базовым классом становится object, чтобы модуль импортировался
# (graceful fallback). Использование класса без torch падает в ensure_torch().
_NN_BASE = nn.Module if nn is not None else object


class GraphEventNet(_NN_BASE):  # type: ignore[misc,valid-type]
    def __init__(self, input_dim: int, num_classes: int) -> None:
        ensure_torch()
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.15),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, num_classes),
        )

    def forward(self, x):  # type: ignore[override]
        return self.net(x)


def ensure_torch() -> None:
    if torch is None or nn is None:
        raise RuntimeError(
            "PyTorch не установлен. Установите зависимости из requirements.txt для ML."
        )


def save_checkpoint(path: str, payload: dict[str, Any]) -> None:
    ensure_torch()
    torch.save(payload, path)


def load_checkpoint(path: str) -> dict[str, Any]:
    ensure_torch()
    return torch.load(path, map_location="cpu")

