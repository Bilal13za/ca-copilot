"""Tests for settings load/save (pure stdlib JSON — no third-party dependency)."""

from ca_copilot import config


def test_defaults_created_and_roundtrip(tmp_path):
    cfg = tmp_path / "config.json"
    s = config.load(cfg)
    assert s["ai"]["model"] == "qwen3:1.7b"
    assert s["ai"]["host"] == "http://127.0.0.1:11434"
    assert cfg.exists()

    s["ai"]["model"] = "qwen3:4b"
    config.save(s, cfg)
    s2 = config.load(cfg)
    assert s2["ai"]["model"] == "qwen3:4b"
    # untouched defaults survive a partial user config
    assert s2["retrieval"]["top_k"] == 5


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{not valid json!!!")
    s = config.load(cfg)
    assert s["ai"]["model"] == "qwen3:1.7b"


def test_partial_config_merges_with_defaults(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"ai": {"model": "x"}}')
    s = config.load(cfg)
    assert s["ai"]["model"] == "x"
    assert s["ai"]["timeout_seconds"] == 120
