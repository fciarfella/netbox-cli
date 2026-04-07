from __future__ import annotations

import os
import time
from pathlib import Path

from netbox_cli.cache import (
    MetadataCache,
    MetadataCacheTTL,
    clear_metadata_cache,
    read_json_cache,
    write_json_cache,
)


def test_read_and_write_json_cache_round_trip(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    payload = {"dcim": "https://netbox.example.com/api/dcim/"}

    write_json_cache(cache_path, payload)

    assert read_json_cache(cache_path) == payload


def test_read_json_cache_respects_ttl(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    write_json_cache(cache_path, {"stale": True})

    old_timestamp = time.time() - 600
    os.utime(cache_path, (old_timestamp, old_timestamp))

    assert read_json_cache(cache_path, max_age_seconds=300) is None


def test_metadata_cache_reads_and_writes_options(tmp_path: Path) -> None:
    cache = MetadataCache(
        tmp_path,
        ttl=MetadataCacheTTL(api_root_seconds=60, schema_seconds=60, options_seconds=60),
    )
    payload = {"actions": {"POST": {"status": {"choices": [{"value": "active"}]}}}}

    cache.write_options("dcim/devices", payload)

    assert cache.read_options("dcim/devices") == payload


def test_read_json_cache_ignores_invalid_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "broken.json"
    cache_path.write_text("{not-json}", encoding="utf-8")

    assert read_json_cache(cache_path) is None


def test_clear_metadata_cache_removes_cached_files(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    write_json_cache(cache_dir / "api_root.json", {"dcim": "https://netbox.example.com/api/dcim/"})
    write_json_cache(cache_dir / "schema.json", {"paths": {}})

    removed_files = clear_metadata_cache(cache_dir)

    assert removed_files == 2
    assert cache_dir.exists()
    assert list(cache_dir.iterdir()) == []
