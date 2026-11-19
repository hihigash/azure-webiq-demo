from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config_loader import load_pack
from backend.schemas import Pack


ROOT = Path(__file__).parents[1]


def test_manufacturing_pack_loads():
    pack = load_pack(ROOT / "config" / "packs" / "manufacturing.json")
    assert pack.id == "manufacturing"
    assert len(pack.allowedDomains) <= 100
    assert len(pack.presets) == 5


def test_pack_rejects_more_than_100_domains():
    data = {
        "id": "bad", "title": "bad", "allowedDomains": [f"domain{i}.example" for i in range(101)],
        "classifications": [], "presets": [{"id": "p", "label": "P", "question": "test"}],
    }
    with pytest.raises(ValidationError):
        Pack.model_validate(data)

