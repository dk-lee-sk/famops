"""famops: shared family operations layer for two-parent households."""

from importlib.resources import files

import yaml

__version__ = "0.1.0"


def load_bundled(name: str) -> dict:
    """Load a YAML file shipped in famops/data."""
    return yaml.safe_load(files("famops.data").joinpath(name).read_text(encoding="utf-8"))
