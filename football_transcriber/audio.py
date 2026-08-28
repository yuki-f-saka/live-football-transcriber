"""Audio input helpers shared by both transcription modes."""

from __future__ import annotations

import sounddevice as sd


def list_input_devices() -> list[tuple[int, str]]:
    """Return (index, name) for every device that has input channels."""
    return [
        (i, d["name"])
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def find_device_index(name: str) -> int:
    """Return the index of the first input device whose name contains ``name``."""
    for i, dev_name in list_input_devices():
        if name in dev_name:
            return i
    available = "\n".join(f"  {i}: {n}" for i, n in list_input_devices())
    raise RuntimeError(f"Device '{name}' not found.\nAvailable:\n{available}")
