"""
_train_salares.py — Fine-tune GaiaSalares head sobre validation CSV.

Usa gaia_v05_amw_ssl4eo_v4.pth como backbone pre-entrenado (ViT-S/16, 12 bandas).
Fine-tunea solo el head (backbone congelado) sobre los 30 puntos de
gaia_salares_v0_1_validation.csv, descargando chips desde GEE.

Guarda: models/gaia_salares_v01.pth

Uso:
    python _train_salares.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import timm

import ee

_MODELS_DIR   = Path(__file__).parent / "models"
_BACKBONE_PTH = _MODELS_DIR / "gaia_v05_amw_ssl4eo_v4.pth"
_OUT_PTH      = _MODELS_DIR / "gaia_salares_v01.pth"
_VAL_CSV      = Path(__file__).parent.parent / "SentinelWatch 2" / "gaia_salares_v0_1_validation.csv"
_CHIP_CACHE   = Path(__file__).parent / "cache" / "chips_salares_train"

_EMBED_DIM    = 384
_INPUT_SIZE   = 224
_S2_SCALE     = 10_000.0
_THRESHOLD    = 0.50
_LR           = 5e-4
_EPOCHS       = 120
_WEIGHT_DECAY = 1e-4

# Bandas S2 en orden para el chip download (12 bandas)
_S2_BANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"]


# ── Arquitectura (idéntica a _GaiaV05Net) ─────────────────────────────────────

class _GaiaSalaresNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.backbone = timm.create_model(
            "vit_small_patch16_224",
            in_chans=12,
            num_classes=0,
            global_pool="token",
            pretrained=False,
        )
        self.classifier = nn.Sequential(
            nn.Linear(_EMBED_DIM, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.backbone(x))


# ── Carga backbone desde gaia_v05 ─────────────────────────────────────────────

def _load_backbone(device: torch.device) -> _GaiaSalaresNet:
    state = torch.load(_BACKBONE_PTH, map_location=device, weights_only=True)
    for key in ("model", "state_dict"):
        if key in state and isinstance(state[key], dict):
            state = state[key]
            break

    model = _GaiaSalaresNet().to(device)
    backbone_sd = {k[len("backbone."):]: v for k, v in state.items() if k.startswith("backbone.")}
    missing, _ = model.backbone.load_state_dict(backbone_sd, strict=False)
    if missing:
        print(f"  Backbone: {len(missing)} claves no encontradas (normal para timm vs checkpoint)")

    for param in model.backbone.parameters():
        param.requires_grad_(False)

    nn.init.kaiming_normal_(model.classifier[0].weight)
    nn.init.kaiming_normal_(model.classifier[3].weight)
    nn.init.zeros_(model.classifier[0].bias)
    nn.init.zeros_(model.classifier[3].bias)

    print(f"  Backbone cargado desde {_BACKBONE_PTH.name} (head reinicializado)")
    return model


# ── Preprocesado chip ──────────────────────────────────────────────────────────

def _preprocess(arr: np.ndarray) -> torch.Tensor:
    arr = np.clip(arr.astype(np.float32) / _S2_SCALE, 0.0, 1.0)
    t = torch.tensor(arr.transpose(2, 0, 1), dtype=torch.float32).unsqueeze(0)
    return nn.functional.interpolate(t, size=(_INPUT_SIZE, _INPUT_SIZE), mode="bilinear", align_corners=False)


def _augment(t: torch.Tensor) -> list[torch.Tensor]:
    return [t, t.flip(-1), t.flip(-2), t.flip(-1).flip(-2)]


# ── Descarga chip desde GEE ────────────────────────────────────────────────────

def _download_chip_gee(lon: float, lat: float) -> np.ndarray | None:
    import ee
    import requests
    import io

    aoi = ee.Geometry.Point([lon, lat])
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate("2026-01-01", "2026-06-23")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .select(_S2_BANDS)
    )
    if col.size().getInfo() == 0:
        col = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filterDate("2024-01-01", "2024-12-31")
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
            .select(_S2_BANDS)
        )

    img    = col.median()
    region = aoi.buffer(320).bounds()
    url    = img.getDownloadURL({"region": region, "scale": 10, "format": "NPY"})
    r      = requests.get(url, timeout=120)
    r.raise_for_status()
    data   = np.load(io.BytesIO(r.content))
    arr    = np.stack([data[b].astype(np.float32) for b in _S2_BANDS], axis=-1)
    return arr


# ── Carga dataset ──────────────────────────────────────────────────────────────

def _load_dataset() -> tuple[list[np.ndarray], list[int]]:
    _CHIP_CACHE.mkdir(parents=True, exist_ok=True)
    chips: list[np.ndarray] = []
    labels: list[int] = []

    with open(_VAL_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"  Descargando chips para {len(rows)} puntos de validación...")
    for i, row in enumerate(rows):
        lat   = float(row["lat"])
        lon   = float(row["lon"])
        label = 1 if row["label"].strip() == "positivo" else 0
        tag   = f"{lat:.5f}_{lon:.5f}"
        cache_path = _CHIP_CACHE / f"{tag}.npy"

        if cache_path.exists():
            chip = np.load(cache_path)
        else:
            try:
                chip = _download_chip_gee(lon, lat)
                np.save(cache_path, chip)
                print(f"    [{i+1}/{len(rows)}] ({lat:.4f},{lon:.4f}) label={label}  shape={chip.shape}")
            except Exception as exc:
                print(f"    [{i+1}/{len(rows)}] SKIP ({lat:.4f},{lon:.4f}): {exc}")
                continue

        if chip is not None and chip.max() > 0:
            chips.append(chip)
            labels.append(label)

    print(f"  Dataset: {len(chips)} chips  ({sum(labels)} positivos / {len(labels)-sum(labels)} negativos)")
    return chips, labels


# ── Entrenamiento ──────────────────────────────────────────────────────────────

def train() -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n[GaiaSalares Train] device={device}")

    credentials = ee.oauth.get_credentials_path()
    ee.Initialize(project="gen-lang-client-0350293091")

    chips, labels = _load_dataset()
    if len(chips) < 10:
        raise RuntimeError(f"Muy pocos chips ({len(chips)}). Revisa conexión GEE.")

    val_n   = max(4, len(chips) // 5)
    idx     = list(range(len(chips)))
    np.random.seed(42)
    np.random.shuffle(idx)
    val_idx  = set(idx[:val_n])
    train_idx = [i for i in idx if i not in val_idx]

    X_train = [chips[i] for i in train_idx]
    y_train = [labels[i] for i in train_idx]
    X_val   = [chips[i] for i in val_idx]
    y_val   = [labels[i] for i in val_idx]

    # Augmentar train con flips
    X_aug, y_aug = [], []
    for chip, lbl in zip(X_train, y_train):
        t = _preprocess(chip)
        for ta in _augment(t):
            X_aug.append(ta)
            y_aug.append(lbl)

    X_val_t = torch.cat([_preprocess(c) for c in X_val]).to(device)
    y_val_t = torch.tensor(y_val, dtype=torch.float32).unsqueeze(1).to(device)

    model     = _load_backbone(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(
        model.classifier.parameters(), lr=_LR, weight_decay=_WEIGHT_DECAY
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=_EPOCHS)

    best_val_acc = 0.0
    best_state   = None

    for epoch in range(1, _EPOCHS + 1):
        model.train()
        perm = torch.randperm(len(X_aug))
        ep_loss = 0.0
        for i in perm:
            x = X_aug[i].to(device)
            y = torch.tensor([[float(y_aug[i])]], dtype=torch.float32).to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            ep_loss += loss.item()
        scheduler.step()

        if epoch % 10 == 0 or epoch == 1:
            model.eval()
            with torch.no_grad():
                preds = (model(X_val_t) > _THRESHOLD).float()
                acc   = (preds == y_val_t).float().mean().item()
            if acc > best_val_acc:
                best_val_acc = acc
                best_state   = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            print(f"  Epoch {epoch:3d}/{_EPOCHS}  loss={ep_loss/len(X_aug):.4f}  val_acc={acc:.2f}  best={best_val_acc:.2f}")

    if best_state is None:
        best_state = {k: v.cpu() for k, v in model.state_dict().items()}

    torch.save(best_state, _OUT_PTH)
    print(f"\nPesos guardados: {_OUT_PTH}  (val_acc={best_val_acc:.2f})")


if __name__ == "__main__":
    train()
