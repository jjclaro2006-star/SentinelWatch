"""
Activity classifier for SentinelWatch using ForestNet as training base.

ForestNet dataset: http://download.cs.stanford.edu/deep/ForestNetDataset.zip
Paper: Irvin et al., NeurIPS 2020 — https://arxiv.org/abs/2011.05479

Architecture: EfficientNet-B2 fine-tuned on ForestNet Landsat 8 RGB chips.
Inference input: Sentinel-2 RGB chips (B4/B3/B2) extracted via Google Earth Engine.
"""

import argparse
import csv
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import requests
import torch
import torch.nn as nn
import timm
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

# ── Label mapping ─────────────────────────────────────────────────────────────

# ForestNet 12-subclass labels → SentinelWatch activity categories.
# "fire" is not in ForestNet; it is detected via dNBR pre-filter at inference time.
FORESTNET_LABEL_MAP: dict[str, str] = {
    "Oil palm plantation":            "agriculture",
    "Timber plantation":              "agriculture",
    "Other large-scale plantations":  "agriculture",
    "Small-scale agriculture":        "agriculture",
    "Small-scale mixed plantation":   "agriculture",
    "Small-scale oil palm plantation":"agriculture",
    "Grassland/shrubland":            "other",
    "Mining":                         "illegal_mining",
    "Logging":                        "logging",
    "Logging road":                   "logging",
    "Fish pond":                      "other",
    "Secondary forest":               "other",
    "Other":                          "other",
    # 4-class fallback labels (used when only coarse labels are available)
    "Plantation":            "agriculture",
    "Smallholder Agriculture": "agriculture",
}

# Classes the CNN predicts (fire is excluded — detected by dNBR rule).
_TRAINABLE_CLASSES = ["agriculture", "illegal_mining", "logging", "other"]
_TRAINABLE_IDX = {c: i for i, c in enumerate(_TRAINABLE_CLASSES)}

# Full output vocabulary including fire.
ACTIVITY_CLASSES = ["agriculture", "illegal_mining", "logging", "fire", "other"]

# ── Constants ─────────────────────────────────────────────────────────────────

# dNBR threshold above which a polygon is classified as fire without CNN inference.
# dNBR = NBR_baseline - NBR_analysis; NBR = (B8 - B12) / (B8 + B12) in Sentinel-2.
FIRE_NBR_THRESHOLD = 0.27

# Sentinel-2 Surface Reflectance values are in [0, 10000].
_S2_SCALE = 10_000.0

_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD  = [0.229, 0.224, 0.225]

FORESTNET_URL = "http://download.cs.stanford.edu/deep/ForestNetDataset.zip"
MODEL_INPUT_SIZE = 224   # EfficientNet-B2 accepts 260 px but 224 is standard.

# ── Dataset ───────────────────────────────────────────────────────────────────

def _map_label(raw: str) -> str | None:
    """Returns SentinelWatch category for a ForestNet label, or None if unknown."""
    label = raw.strip()
    if label in FORESTNET_LABEL_MAP:
        return FORESTNET_LABEL_MAP[label]
    for k, v in FORESTNET_LABEL_MAP.items():
        if k.lower() == label.lower():
            return v
    return None


class ForestNetDataset(Dataset):
    def __init__(self, image_paths: list[Path], labels: list[str], transform=None):
        self.image_paths = image_paths
        self.labels = [_TRAINABLE_IDX[l] for l in labels]
        self.transform = transform

    def __len__(self) -> int:
        return len(self.image_paths)

    def __getitem__(self, idx):
        img = Image.open(self.image_paths[idx]).convert("RGB")
        if self.transform:
            img = self.transform(img)
        return img, self.labels[idx]


def _build_transforms(train: bool) -> transforms.Compose:
    if train:
        return transforms.Compose([
            transforms.Resize((MODEL_INPUT_SIZE, MODEL_INPUT_SIZE)),
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            transforms.Normalize(_IMAGENET_MEAN, _IMAGENET_STD),
        ])
    return transforms.Compose([
        transforms.Resize((MODEL_INPUT_SIZE, MODEL_INPUT_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(_IMAGENET_MEAN, _IMAGENET_STD),
    ])


def download_forestnet(dest_dir: str | Path = "./forestnet_data") -> Path:
    """Downloads and extracts the ForestNet dataset (~500 MB)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "ForestNetDataset.zip"

    if not zip_path.exists():
        print(f"Downloading ForestNet dataset → {zip_path}")
        with requests.get(FORESTNET_URL, stream=True, timeout=300) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        print(f"\r  {downloaded / total * 100:.1f}%", end="", flush=True)
        print()

    # The zip extracts into a nested path; find the dir that contains train.csv.
    train_csv_hits = list(dest_dir.rglob("train.csv"))
    if train_csv_hits:
        return train_csv_hits[0].parent

    print(f"Extracting → {dest_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)

    train_csv_hits = list(dest_dir.rglob("train.csv"))
    if not train_csv_hits:
        raise FileNotFoundError(
            f"Could not find train.csv after extracting {zip_path}. "
            "The zip layout may have changed — inspect the contents manually."
        )
    return train_csv_hits[0].parent


def load_forestnet_dataset(
    data_dir: str | Path,
    batch_size: int = 32,
) -> tuple[DataLoader, DataLoader]:
    """
    Parses the ForestNet directory and returns (train_loader, val_loader).

    Expects the ForestNet layout:
      <data_dir>/train.csv, val.csv   — columns: label, merged_label, example_path, ...
      <data_dir>/examples/<lat>_<lon>/images/visible/composite.png

    Falls back to directory-based layout: train/<class>/<images>.
    """
    data_dir = Path(data_dir)
    if (data_dir / "train.csv").exists():
        return _load_forestnet_csvs(data_dir, batch_size)
    return _load_from_dirs(data_dir, batch_size)


def _read_forestnet_csv(csv_path: Path, data_dir: Path) -> tuple[list[Path], list[str]]:
    """Parses one ForestNet split CSV and returns (image_paths, activity_labels).

    ForestNet CSV columns: label, merged_label, latitude, longitude, year, example_path
    Image path per row: <data_dir>/<example_path>/images/visible/composite.png
    Uses fine-grained `label` column for the 12-subclass mapping.
    """
    paths, labels = [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_lbl      = row.get("label", "").strip()
            example_path = row.get("example_path", "").strip()
            if not raw_lbl or not example_path:
                continue
            activity = _map_label(raw_lbl)
            if activity is None or activity == "fire":
                continue
            img_path = data_dir / example_path / "images" / "visible" / "composite.png"
            if not img_path.exists():
                continue
            paths.append(img_path)
            labels.append(activity)
    return paths, labels


def _load_forestnet_csvs(data_dir: Path, batch_size: int) -> tuple[DataLoader, DataLoader]:
    train_paths, train_labels = _read_forestnet_csv(data_dir / "train.csv", data_dir)
    val_paths,   val_labels   = _read_forestnet_csv(data_dir / "val.csv",   data_dir)

    if not train_paths:
        raise FileNotFoundError(
            f"No training images found under {data_dir}.\n"
            "Check that examples/<lat>_<lon>/images/visible/composite.png files exist."
        )

    _print_split("Train", train_labels)
    _print_split("Val",   val_labels)

    return _make_loaders(train_paths, train_labels, val_paths, val_labels, batch_size)


def _load_from_dirs(data_dir: Path, batch_size: int) -> tuple[DataLoader, DataLoader]:
    IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

    def gather(split_dir: Path):
        paths, labels = [], []
        if not split_dir.exists():
            return paths, labels
        for cls_dir in sorted(split_dir.iterdir()):
            if not cls_dir.is_dir():
                continue
            activity = _map_label(cls_dir.name)
            if activity is None or activity == "fire":
                continue
            for img in cls_dir.iterdir():
                if img.suffix.lower() in IMG_EXTS:
                    paths.append(img)
                    labels.append(activity)
        return paths, labels

    train_dir = data_dir / "train"
    if not train_dir.exists():
        raise FileNotFoundError(
            f"Neither a CSV file nor a 'train/' directory found in {data_dir}.\n"
            "Run: python classifier.py --download --data-dir ./forestnet_data\n"
            "Then inspect the extracted folder structure."
        )

    train_paths, train_labels = gather(train_dir)
    val_paths,   val_labels   = gather(data_dir / "val")

    _print_split("Train", train_labels)
    _print_split("Val",   val_labels)

    return _make_loaders(train_paths, train_labels, val_paths, val_labels, batch_size)


def _make_loaders(
    train_paths, train_labels, val_paths, val_labels, batch_size
) -> tuple[DataLoader, DataLoader]:
    train_ds = ForestNetDataset(train_paths, train_labels, _build_transforms(True))
    val_ds   = ForestNetDataset(val_paths,   val_labels,   _build_transforms(False))
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,  num_workers=2)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False, num_workers=2)
    return train_loader, val_loader


def _print_split(name: str, labels: list[str]) -> None:
    counts = Counter(labels)
    dist = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"  {name} ({sum(counts.values())} samples): {dist}")


# ── Classifier ────────────────────────────────────────────────────────────────

class ActivityClassifier:
    """
    EfficientNet-B2 image classifier for deforestation activity type.

    Trained on ForestNet (Landsat 8 RGB chips, Indonesia) and applied at
    inference time to Sentinel-2 RGB chips (B4/B3/B2) from Google Earth Engine.

    Predicted classes: agriculture | illegal_mining | logging | fire | other
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        device: str | None = None,
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        self.model = timm.create_model(
            "efficientnet_b2",
            pretrained=(model_path is None),
            num_classes=len(_TRAINABLE_CLASSES),
        )
        self.model.to(self.device)

        if model_path is not None:
            state = torch.load(model_path, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state)
            print(f"Loaded weights from {model_path}")

        self._transform = _build_transforms(train=False)

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(
        self,
        chip_rgb: np.ndarray,
        dnbr: float | None = None,
    ) -> tuple[str, float]:
        """
        Classifies a single image chip.

        Args:
            chip_rgb: Array [H, W, 3] — Sentinel-2 B4/B3/B2.
                      Accepts uint16 in [0, 10000] or float32 in [0, 1].
            dnbr:     Optional dNBR value for the polygon.
                      Values > FIRE_NBR_THRESHOLD (0.27) return ("fire", confidence)
                      without running the CNN.

        Returns:
            (activity_type, confidence) where confidence ∈ [0, 1].
        """
        if dnbr is not None and dnbr > FIRE_NBR_THRESHOLD:
            return "fire", round(float(min(dnbr / 0.5, 1.0)), 4)

        tensor = self._preprocess(chip_rgb).unsqueeze(0).to(self.device)
        probs = self._forward(tensor)[0]
        idx = int(probs.argmax())
        return _TRAINABLE_CLASSES[idx], round(float(probs[idx]), 4)

    def predict_batch(
        self,
        chips: list[np.ndarray],
        dnbr_values: list[float | None] | None = None,
    ) -> list[tuple[str, float]]:
        """
        Batch inference. Chips flagged as fire via dNBR skip the CNN.

        Args:
            chips:       List of [H, W, 3] arrays.
            dnbr_values: Optional per-chip dNBR values (same length as chips).

        Returns:
            List of (activity_type, confidence) tuples.
        """
        if dnbr_values is None:
            dnbr_values = [None] * len(chips)

        results: list[tuple[str, float] | None] = [None] * len(chips)
        ml_indices: list[int] = []

        for i, (chip, dnbr) in enumerate(zip(chips, dnbr_values)):
            if dnbr is not None and dnbr > FIRE_NBR_THRESHOLD:
                results[i] = ("fire", round(float(min(dnbr / 0.5, 1.0)), 4))
            else:
                ml_indices.append(i)

        if ml_indices:
            tensors = torch.stack(
                [self._preprocess(chips[i]) for i in ml_indices]
            ).to(self.device)
            probs_batch = self._forward(tensors)
            for j, i in enumerate(ml_indices):
                probs = probs_batch[j]
                idx = int(probs.argmax())
                results[i] = (_TRAINABLE_CLASSES[idx], round(float(probs[idx]), 4))

        return results  # type: ignore[return-value]

    def _preprocess(self, chip: np.ndarray) -> torch.Tensor:
        arr = chip.astype(np.float32)
        if arr.max() > 1.0:
            arr = arr / _S2_SCALE
        arr = np.clip(arr, 0.0, 1.0)
        img = Image.fromarray((arr * 255).astype(np.uint8))
        return self._transform(img)

    def _forward(self, tensors: torch.Tensor) -> torch.Tensor:
        self.model.eval()
        with torch.no_grad():
            return torch.softmax(self.model(tensors), dim=-1).cpu()

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        data_dir: str | Path,
        epochs: int = 15,
        batch_size: int = 32,
        lr: float = 1e-4,
        output_path: str | Path = "forestnet_weights.pth",
    ) -> None:
        """Fine-tunes EfficientNet-B2 on ForestNet data."""
        from torch.optim import AdamW
        from torch.optim.lr_scheduler import CosineAnnealingLR

        output_path = Path(output_path)
        train_loader, val_loader = load_forestnet_dataset(data_dir, batch_size)
        optimizer = AdamW(self.model.parameters(), lr=lr, weight_decay=1e-4)
        scheduler = CosineAnnealingLR(optimizer, T_max=epochs)
        criterion = nn.CrossEntropyLoss()
        best_val_acc = 0.0

        for epoch in range(1, epochs + 1):
            self.model.train()
            total_loss = correct = total = 0

            for imgs, labels in train_loader:
                imgs, labels = imgs.to(self.device), labels.to(self.device)
                optimizer.zero_grad()
                logits = self.model(imgs)
                loss = criterion(logits, labels)
                loss.backward()
                optimizer.step()
                total_loss += loss.item() * len(labels)
                correct += (logits.argmax(1) == labels).sum().item()
                total += len(labels)

            scheduler.step()
            val_acc = self._evaluate(val_loader)
            print(
                f"Epoch {epoch:3d}/{epochs} | "
                f"loss={total_loss / total:.4f} | "
                f"train_acc={correct / total:.3f} | "
                f"val_acc={val_acc:.3f}"
            )

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                torch.save(self.model.state_dict(), output_path)
                print(f"  → Best model saved: {output_path}")

        print(f"Training complete. Best val accuracy: {best_val_acc:.3f}")

    def _evaluate(self, loader: DataLoader) -> float:
        self.model.eval()
        correct = total = 0
        with torch.no_grad():
            for imgs, labels in loader:
                imgs, labels = imgs.to(self.device), labels.to(self.device)
                correct += (self.model(imgs).argmax(1) == labels).sum().item()
                total += len(labels)
        return correct / total if total else 0.0


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ForestNet activity classifier for SentinelWatch")
    parser.add_argument("--download",  action="store_true", help="Download ForestNet dataset")
    parser.add_argument("--train",     action="store_true", help="Train the classifier")
    parser.add_argument("--data-dir",  default="./forestnet_data", metavar="DIR")
    parser.add_argument("--epochs",    type=int, default=15)
    parser.add_argument("--batch-size",type=int, default=32)
    parser.add_argument("--output",    default="forestnet_weights.pth", metavar="PATH")
    parser.add_argument("--weights",   default=None, metavar="PATH",
                        help="Weights for inference smoke-test")
    args = parser.parse_args()

    if args.download:
        extract_dir = download_forestnet(args.data_dir)
        print(f"Dataset ready at: {extract_dir}")
        print("\nTop-level contents:")
        for p in sorted(extract_dir.iterdir()):
            print(f"  {p.name}")

    if args.train:
        clf = ActivityClassifier()
        clf.train(
            data_dir=args.data_dir,
            epochs=args.epochs,
            batch_size=args.batch_size,
            output_path=args.output,
        )

    if not args.download and not args.train:
        weights = args.weights or (args.output if Path(args.output).exists() else None)
        clf = ActivityClassifier(model_path=weights)
        dummy = np.random.randint(0, 5000, (64, 64, 3), dtype=np.uint16)
        activity, confidence = clf.predict(dummy)
        print(f"Smoke test → activity: {activity}, confidence: {confidence}")
        # Fire pre-filter test
        activity_fire, conf_fire = clf.predict(dummy, dnbr=0.35)
        print(f"Fire test  → activity: {activity_fire}, confidence: {conf_fire}")
