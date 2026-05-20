"""
Disk-based JSON cache for API responses.

Key conventions:
  pubmed_xml:<pmid>       – raw PubMed XML string for a single PMID
  pmcid_lookup:<pmid>     – PMCID resolution result
  oa_check:<pmcid>        – PMC OA availability metadata
  fulltext:<pmcid>        – full-text XML string
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _safe_filename(key: str) -> str:
    """Convert an arbitrary cache key to a safe filename."""
    # replace path-unsafe chars; keep short keys readable
    safe = key.replace(":", "_").replace("/", "_").replace(" ", "_")
    if len(safe) > 120:
        safe = safe[:80] + "_" + hashlib.md5(key.encode()).hexdigest()[:16]
    return safe + ".json"


class Cache:
    """Simple file-based key→JSON store."""

    def __init__(self, cache_dir: Path, force_refresh: bool = False):
        self.cache_dir = cache_dir
        self.force_refresh = force_refresh
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / _safe_filename(key)

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if missing / force_refresh is set."""
        if self.force_refresh:
            return None
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache read error for %r: %s", key, exc)
            return None

    def set(self, key: str, value: Any) -> None:
        """Persist value as JSON."""
        p = self._path(key)
        try:
            p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.warning("Cache write error for %r: %s", key, exc)

    def has(self, key: str) -> bool:
        return not self.force_refresh and self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()
