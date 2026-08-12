from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_MANIFEST = Path(__file__).with_name("messy-layouts.json")


def load_fixture_manifest() -> dict[str, Any]:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("fixtures"), list):
        raise ValueError("synthetic audiobook fixture manifest is invalid")
    return payload


def build_fixture(root: str | Path, name: str, *, content: bytes = b"synthetic-audio") -> tuple[Path, ...]:
    root_path = Path(root)
    manifest = load_fixture_manifest()
    fixture = next((item for item in manifest["fixtures"] if item.get("name") == name), None)
    if fixture is None:
        known = ", ".join(sorted(str(item.get("name")) for item in manifest["fixtures"]))
        raise ValueError(f"unknown fixture {name!r}; available: {known}")

    created: list[Path] = []
    for relative in fixture.get("tree", []):
        destination = root_path / Path(str(relative))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        created.append(destination)
    return tuple(created)
