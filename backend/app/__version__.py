"""The backend's version.

Written by ``scripts/bump_version.py`` from the repository's root ``VERSION``
file and asserted by ``scripts/validate_versions.py``, so this is derived state
— edit ``VERSION`` and re-run the bump script rather than changing it here.

A module rather than ``importlib.metadata.version("app")``: that reads metadata
uv generates while installing the workspace package, which is true in the image
but is an implementation detail of the packaging step, and it raises
``PackageNotFoundError`` anywhere the package is merely on ``sys.path`` — tests
run from a source checkout included.
"""

__version__ = "0.12.0"
