from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import numpy as np

from web_portal.lib.ml.features import FEATURE_ORDER
from web_portal.lib.ml.model import GraphEventNet, ensure_torch

try:
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
except Exception:  # pragma: no cover
    classification_report = None  # type: ignore[assignment]
    confusion_matrix = None  # type: ignore[assignment]
    train_test_split = None  # type: ignore[assignment]

try:
    import torch
    import torch.nn.functional as F
except Exception:  # pragma: no cover
    torch = None
    F = None


@dataclass
class TrainResult:
    state_dict: dict[str, Any]
    labels: list[str]
    mean: list[float]
    std: list[float]
    metrics: dict[str, Any]


def _f1_macro(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> float:
    f1s: list[float] = []
    for c in range(n_classes):
        tp = float(np.sum((y_true == c) & (y_pred == c)))
        fp = float(np.sum((y_true != c) & (y_pred == c)))
        fn = float(np.sum((y_true == c) & (y_pred != c)))
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2.0 * p * r / (p + r) if (p + r) else 0.0
        f1s.append(f1)
    return float(np.mean(f1s) if f1s else 0.0)


def _fit_standardize(
    x_train: np.ndarray, x_val: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    xtr = (x_train - mean) / std
    xva = (x_val - mean) / std
    return xtr, xva, mean, std


def _val_metrics_dict(
    y_va: np.ndarray, pred: np.ndarray, label_names: list[str]
) -> dict[str, Any]:
    if classification_report is None or confusion_matrix is None:
        acc = float(np.mean(pred == y_va)) if len(y_va) else 0.0
        f1 = _f1_macro(y_va, pred, len(label_names))
        return {
            "val_accuracy": round(acc, 6),
            "val_f1_macro": round(f1, 6),
        }
    acc = float(np.mean(pred == y_va)) if len(y_va) else 0.0
    f1 = _f1_macro(y_va, pred, len(label_names))
    rep = classification_report(
        y_va,
        pred,
        labels=list(range(len(label_names))),
        target_names=label_names,
        output_dict=True,
        zero_division=0,
    )
    per_class: dict[str, Any] = {}
    for name in label_names:
        if name in rep and isinstance(rep[name], dict):
            per_class[name] = {
                "precision": round(float(rep[name].get("precision", 0)), 4),
                "recall": round(float(rep[name].get("recall", 0)), 4),
                "f1": round(float(rep[name].get("f1-score", 0)), 4),
            }
    cm = confusion_matrix(
        y_va, pred, labels=list(range(len(label_names)))
    ).tolist()
    return {
        "val_accuracy": round(acc, 6),
        "val_f1_macro": round(f1, 6),
        "val_f1_weighted": round(float(rep.get("weighted avg", {}).get("f1-score", 0)), 6),
        "per_class": per_class,
        "confusion_matrix": cm,
    }


def train_multiclass(
    x: list[list[float]],
    y_labels: list[str],
    *,
    epochs: int = 60,
    lr: float = 1e-3,
    weight_decay: float = 0.0,
    val_split: str = "stratified",
    val_size: float = 0.2,
    random_seed: int = 42,
) -> TrainResult:
    """
    Обучение GraphEventNet.

    val_split: ``stratified`` (рекомендуется при дисбалансе) или ``time`` (первые
    80% по порядку примеров — train, хвост — val; без перемешивания).
    Нормализация признаков — только на train, затем применяется к val.
    """
    ensure_torch()
    if torch is None or F is None:
        raise RuntimeError(
            "PyTorch не установлен. Установите зависимости из requirements.txt для ML."
        )
    if train_test_split is None:
        raise RuntimeError("scikit-learn недоступен; проверьте requirements.txt")
    if not x or not y_labels or len(x) != len(y_labels):
        raise ValueError("Пустой train dataset")
    labels = sorted({str(v) for v in y_labels})
    if len(labels) < 2:
        raise ValueError("Для обучения нужно минимум 2 класса")
    label_to_idx = {k: i for i, k in enumerate(labels)}
    y = np.array([label_to_idx[str(v)] for v in y_labels], dtype=np.int64)
    X = np.array(x, dtype=np.float32)
    n = len(X)
    if n < 2:
        raise ValueError("Недостаточно примеров")

    val_split_norm = str(val_split or "stratified").strip().lower()
    if val_split_norm not in ("stratified", "time"):
        raise ValueError("val_split должен быть 'stratified' или 'time'")

    if val_split_norm == "time":
        split = int(n * (1.0 - float(val_size)))
        split = min(max(1, split), n - 1)
        idx_tr = np.arange(0, split)
        idx_va = np.arange(split, n)
    else:
        test_sz = float(val_size)
        test_sz = min(max(0.05, test_sz), 0.5)
        try:
            idx_tr, idx_va = train_test_split(
                np.arange(n),
                test_size=test_sz,
                stratify=y,
                random_state=int(random_seed),
            )
        except ValueError:
            split = int(n * (1.0 - test_sz))
            split = min(max(1, split), n - 1)
            idx_tr = np.arange(0, split)
            idx_va = np.arange(split, n)

    x_tr_raw = X[idx_tr]
    x_va_raw = X[idx_va]
    y_tr = y[idx_tr]
    y_va = y[idx_va]

    x_tr, x_va, mean, std = _fit_standardize(x_tr_raw, x_va_raw)

    torch.manual_seed(int(random_seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(random_seed))

    model = GraphEventNet(input_dim=len(FEATURE_ORDER), num_classes=len(labels))
    opt = torch.optim.Adam(
        model.parameters(),
        lr=float(lr),
        weight_decay=float(weight_decay),
    )
    cls_counts = np.bincount(y_tr, minlength=len(labels)).astype(np.float32)
    cls_weights = np.where(
        cls_counts > 0, cls_counts.sum() / np.maximum(cls_counts, 1), 1.0
    )
    weight_t = torch.tensor(cls_weights, dtype=torch.float32)

    xtr_t = torch.tensor(x_tr, dtype=torch.float32)
    ytr_t = torch.tensor(y_tr, dtype=torch.long)
    xva_t = torch.tensor(x_va, dtype=torch.float32)
    yva_t = torch.tensor(y_va, dtype=torch.long)

    best_val = -1.0
    best_state = None
    n_epochs = max(5, int(epochs))
    for _ in range(n_epochs):
        model.train()
        logits = model(xtr_t)
        loss = F.cross_entropy(logits, ytr_t, weight=weight_t)
        opt.zero_grad()
        loss.backward()
        opt.step()

        model.eval()
        with torch.no_grad():
            val_logits = model(xva_t)
            val_pred = torch.argmax(val_logits, dim=1).cpu().numpy()
            f1 = _f1_macro(y_va, val_pred, len(labels))
            if f1 >= best_val:
                best_val = f1
                best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}

    if best_state is None:
        best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        logits = model(xva_t)
        pred = torch.argmax(logits, dim=1).cpu().numpy()

    metrics = _val_metrics_dict(y_va, pred, labels)
    metrics.update(
        {
            "val_split": val_split_norm,
            "val_size": float(val_size),
            "random_seed": int(random_seed),
            "weight_decay": float(weight_decay),
            "train_size": int(len(y_tr)),
            "val_size_samples": int(len(y_va)),
        }
    )

    return TrainResult(
        state_dict=best_state,
        labels=labels,
        mean=mean.astype(np.float32).tolist(),
        std=std.astype(np.float32).tolist(),
        metrics=metrics,
    )
