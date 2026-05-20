"""
Runtime configuration for the ArmLifeBank pipeline.

Priority (highest to lowest):
  1. CLI arguments (applied in cli.py after Config is constructed)
  2. Environment variables
  3. config.yaml
  4. Built-in defaults
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

# Repository root = parent of this file's parent
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROFILES_DIR = _REPO_ROOT / "country_profiles"

logger = logging.getLogger(__name__)


def load_country_profile(code: str, profiles_dir: Path = _PROFILES_DIR) -> dict:
    """Load and return the country profile YAML for *code* (e.g. 'armenia')."""
    path = profiles_dir / f"{code}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in profiles_dir.glob("*.yaml"))
        raise FileNotFoundError(
            f"Country profile '{code}' not found in {profiles_dir}. "
            f"Available profiles: {available}"
        )
    return _load_yaml(path)


def _read_api_key_file(path: Path) -> Optional[str]:
    """Return stripped contents of an API key file, or None if absent/empty."""
    try:
        key = path.read_text(encoding="utf-8").strip()
        return key if key else None
    except FileNotFoundError:
        return None


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Config:
    """Central configuration object. Construct once and pass around."""

    def __init__(
        self,
        config_file: Optional[Path] = None,
        country: Optional[str] = None,
    ):
        cfg_path = config_file or (_REPO_ROOT / "config.yaml")
        raw = _load_yaml(cfg_path)

        # ── NCBI credentials ─────────────────────────────────────────────
        ncbi = raw.get("ncbi", {})
        self.ncbi_email: str = os.environ.get(
            "NCBI_EMAIL", ncbi.get("email", "arakelyanaa@gmail.com")
        )
        self.ncbi_tool: str = os.environ.get(
            "NCBI_TOOL", ncbi.get("tool", "armlifebank")
        )

        # API key: env var > NCBI_API.txt > config.yaml key (not recommended)
        api_key_file = _REPO_ROOT / raw.get("paths", {}).get(
            "api_key_file", "NCBI_API.txt"
        )
        self.ncbi_api_key: Optional[str] = (
            os.environ.get("NCBI_API_KEY")
            or _read_api_key_file(api_key_file)
            or ncbi.get("api_key")
        )

        self.rate_delay: float = float(ncbi.get("rate_delay", 0.12))
        self.batch_size: int = int(ncbi.get("batch_size", 200))
        self.max_retries: int = int(ncbi.get("max_retries", 5))
        self.retry_backoff: float = float(ncbi.get("retry_backoff", 2.0))

        # ── Country profile ──────────────────────────────────────────────
        # Priority: constructor kwarg > env var > config.yaml > "armenia"
        cfg_country = raw.get("country", "armenia")
        self.country_code: str = (
            country
            or os.environ.get("ALB_COUNTRY")
            or cfg_country
        )
        self.country_profile: dict = load_country_profile(self.country_code)

        # ── Search parameters ────────────────────────────────────────────
        search = raw.get("search", {})
        self.start_year: int = int(
            os.environ.get("ALB_START_YEAR", search.get("start_year", 2020))
        )
        self.end_year: int = int(
            os.environ.get("ALB_END_YEAR", search.get("end_year", 2025))
        )
        # query_template: country profile is authoritative; config.yaml is fallback
        if "search_term" in self.country_profile:
            self.query_template: str = self.country_profile["search_term"]
        else:
            country_name = self.country_profile.get("name", self.country_code.capitalize())
            self.query_template = search.get(
                "query_template",
                f'("{country_name}"[Affiliation]) AND ({{year}}[PDAT])',
            )

        # ── Pipeline behaviour ───────────────────────────────────────────
        pipeline = raw.get("pipeline", {})
        self.mode: str = os.environ.get(
            "ALB_MODE", pipeline.get("mode", "strict")
        )
        sample_env = os.environ.get("ALB_SAMPLE_SIZE")
        cfg_sample = pipeline.get("sample_size")
        self.sample_size: Optional[int] = (
            int(sample_env) if sample_env else (int(cfg_sample) if cfg_sample else None)
        )
        self.resume: bool = bool(pipeline.get("resume", False))
        self.force_refresh_cache: bool = bool(
            pipeline.get("force_refresh_cache", False)
        )

        # ── Paths ────────────────────────────────────────────────────────
        paths = raw.get("paths", {})
        default_output = f"output/{self.country_code}"
        self.output_dir: Path = _REPO_ROOT / paths.get("output_dir", default_output)
        self.cache_dir: Path = _REPO_ROOT / paths.get("cache_dir", ".cache")
        self.log_dir: Path = _REPO_ROOT / paths.get("log_dir", "logs")
        self.repository_patterns: Path = _REPO_ROOT / paths.get(
            "repository_patterns", "repository_patterns.yaml"
        )

    def ensure_dirs(self) -> None:
        """Create output, cache, and log directories if they don't exist."""
        for d in (self.output_dir, self.cache_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    def apply_cli_overrides(
        self,
        *,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        mode: Optional[str] = None,
        sample_size: Optional[int] = None,
        resume: Optional[bool] = None,
        force_refresh_cache: Optional[bool] = None,
        output_dir: Optional[str] = None,
        log_level: Optional[str] = None,
    ) -> None:
        """Patch config with values passed from the CLI.

        Note: country is resolved at construction time (passed to __init__),
        not here, because it affects profile loading and the default output dir.
        """
        if start_year is not None:
            self.start_year = start_year
        if end_year is not None:
            self.end_year = end_year
        if mode is not None:
            self.mode = mode
        if sample_size is not None:
            self.sample_size = sample_size
        if resume is not None:
            self.resume = resume
        if force_refresh_cache is not None:
            self.force_refresh_cache = force_refresh_cache
        if output_dir is not None:
            self.output_dir = Path(output_dir)
        self._log_level = log_level or "INFO"

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Config(country={self.country_code!r}, "
            f"years={self.start_year}-{self.end_year}, "
            f"mode={self.mode!r}, sample_size={self.sample_size}, "
            f"api_key={'set' if self.ncbi_api_key else 'NOT SET'})"
        )
