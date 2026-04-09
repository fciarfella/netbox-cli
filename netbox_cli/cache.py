"""Helpers for lightweight metadata caching."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def read_json_cache(path: Path, *, max_age_seconds: int | None = None) -> dict[str, Any] | None:
    """Read a JSON cache file if it exists and is still fresh."""

    if not path.exists():
        return None

    if max_age_seconds is not None:
        age_seconds = time.time() - path.stat().st_mtime
        if age_seconds >= max_age_seconds:
            return None

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def write_json_cache(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON cache data, creating the parent directory if needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def cache_key_to_path(cache_dir: Path, cache_key: str) -> Path:
    """Map a logical cache key to a stable JSON file path."""

    safe_key = cache_key.replace("/", "__")
    return cache_dir / f"{safe_key}.json"


@dataclass(frozen=True, slots=True)
class MetadataCacheTTL:
    """TTL values for cached NetBox metadata."""

    api_root_seconds: int = 300
    schema_seconds: int = 3600
    options_seconds: int = 1800


@dataclass(slots=True)
class MetadataCache:
    """Small file-backed cache for discovery metadata."""

    cache_dir: Path
    ttl: MetadataCacheTTL = field(default_factory=MetadataCacheTTL)

    def read_api_root(self) -> dict[str, Any] | None:
        return read_json_cache(
            self.cache_dir / "api_root.json",
            max_age_seconds=self.ttl.api_root_seconds,
        )

    def write_api_root(self, payload: Mapping[str, Any]) -> None:
        write_json_cache(self.cache_dir / "api_root.json", payload)

    def read_schema(self) -> dict[str, Any] | None:
        return read_json_cache(
            self.cache_dir / "schema.json",
            max_age_seconds=self.ttl.schema_seconds,
        )

    def write_schema(self, payload: Mapping[str, Any]) -> None:
        write_json_cache(self.cache_dir / "schema.json", payload)

    def read_options(self, endpoint_path: str) -> dict[str, Any] | None:
        return read_json_cache(
            self._options_path(endpoint_path),
            max_age_seconds=self.ttl.options_seconds,
        )

    def write_options(self, endpoint_path: str, payload: Mapping[str, Any]) -> None:
        write_json_cache(self._options_path(endpoint_path), payload)

    def _options_path(self, endpoint_path: str) -> Path:
        normalized = endpoint_path.strip("/") or "root"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("_") or "endpoint"
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
        return self.cache_dir / f"options__{slug}__{digest}.json"


def metadata_cache_for_profile(
    cache_dir: Path,
    profile_name: str | None,
) -> MetadataCache:
    """Return a metadata cache scoped to one profile when available."""

    if profile_name is None:
        return MetadataCache(cache_dir)

    normalized_name = re.sub(r"[^A-Za-z0-9._-]+", "_", profile_name.strip()).strip("_")
    if not normalized_name:
        return MetadataCache(cache_dir)

    return MetadataCache(cache_dir / "profiles" / normalized_name)


def clear_metadata_cache(cache_dir: Path) -> int:
    """Remove cached metadata files and recreate the cache directory."""

    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        return 0

    removed_files = sum(1 for path in cache_dir.rglob("*") if path.is_file())
    shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return removed_files
