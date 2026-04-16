"""gencon-audiobook: Download General Conference talks as m4b audiobook and epub."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gencon-audiobook")
except PackageNotFoundError:
    __version__ = "unknown"  # running from source without pip install
