"""Application settings.

Settings live in <data_dir>/config.json (created with safe defaults on first
run). Plain JSON via the standard library — no third-party dependency, so
installation never needs a C compiler. Nothing is sent anywhere; the AI
provider is always localhost.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

from . import paths

DEFAULTS: Dict[str, Any] = {
    # Local AI (Ollama). The provider interface is modular; see ai.py.
    "ai": {
        "provider": "ollama",
        "host": "http://127.0.0.1:11434",
        "model": "qwen3:1.7b",
        "timeout_seconds": 120,
        "max_context_chars": 12000,  # retrieved text fed to the model
        "temperature": 0.2,
        "stream": True,
    },
    # Retrieval: how much document text grounds an answer.
    "retrieval": {
        "top_k": 5,
        "chunk_chars": 1500,
        "chunk_overlap_chars": 200,
    },
    # Reconciliation defaults.
    "reconciliation": {
        "amount_tolerance": 0.01,
        "date_tolerance_days": 0,
    },
    # OCR for scanned PDFs: off unless the user enables it AND tesseract is installed.
    "ocr": {
        "enabled": False,
        "tesseract_cmd": "",  # empty = auto-detect on PATH
        "dpi": 200,
    },
    "app": {
        "language": "en",
        "theme": "light",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load(config_file: Path | str | None = None) -> Dict[str, Any]:
    """Load settings, creating config.json with safe defaults if absent."""
    cfg_file = Path(config_file) if config_file else paths.config_path()
    settings = copy.deepcopy(DEFAULTS)
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as fh:
                user = json.load(fh) or {}
            if not isinstance(user, dict):
                raise ValueError("config must be a JSON object")
            settings = _deep_merge(settings, user)
        except Exception:
            # A corrupt config must never prevent startup; fall back to defaults.
            pass
    else:
        save(settings, cfg_file)
    return settings


def save(settings: Dict[str, Any], config_file: Path | str | None = None) -> None:
    cfg_file = Path(config_file) if config_file else paths.config_path()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    # Pure JSON (no comments — the stdlib parser rejects them). A short
    # explanation of each section lives in config.example.json.
    with open(cfg_file, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
