"""Explicit clean environments for real CI subprocess fixtures."""
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[1]


def _reviewed_directory(value, relative):
    expected = REPO_ROOT / relative
    supplied = Path(value)
    if (not supplied.is_absolute() or supplied != expected.absolute()
            or not supplied.is_dir() or supplied.resolve() != expected.absolute()):
        raise ValueError("CI subprocess runtime must use the reviewed repository artifact directory")
    return str(supplied)


def child_environment(*, pythonpath=None, tmpdir=None):
    environment = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    # Only the outer isolation launcher's explicitly selected native SQLite
    # artifacts survive. No provider keys or unrelated parent variables do.
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        if os.environ.get(name):
            environment[name] = _reviewed_directory(os.environ[name], ".ci/sqlite/lib")
    native = os.environ.get("QUARRY_CI_SQLITE_EXTENSION_ROOT")
    if native:
        native = _reviewed_directory(native, ".ci/sqlite/python")
        environment["QUARRY_CI_SQLITE_EXTENSION_ROOT"] = native
    if pythonpath is not None:
        environment["PYTHONPATH"] = str(pythonpath)
    if native:
        environment["PYTHONPATH"] = native + (os.pathsep + environment["PYTHONPATH"]
                                               if environment.get("PYTHONPATH") else "")
    if tmpdir is not None:
        environment["TMPDIR"] = str(tmpdir)
    return environment
