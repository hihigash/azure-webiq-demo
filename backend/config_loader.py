from __future__ import annotations

import json
from pathlib import Path

from .schemas import Pack, Pricing


def load_pack(path: str | Path) -> Pack:
    return Pack.model_validate(_read(path))


def load_pricing(path: str | Path) -> Pricing:
    return Pricing.model_validate(_read(path))


def _read(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} はJSONオブジェクトである必要があります")
    return data

