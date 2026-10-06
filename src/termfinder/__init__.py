"""Reproducible research term collection. Importing makes no network calls."""
__version__ = "6.4.0"

from .project import Project
from .providers import FakeProvider, Response

__all__ = ["Project", "FakeProvider", "Response", "__version__"]
