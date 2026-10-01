"""
Secure Path Resolution for MASTERDB.

Protects against path traversal attacks (e.g., ../../secret.txt, /etc/passwd, C:\\Windows\\...)
by canonicalizing paths and verifying they remain within configured, permitted root directories.
"""
import os
from pathlib import Path
from typing import Iterable, List, Optional, Union

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class PathTraversalError(ValueError):
    """Raised when a resolved path escapes all permitted root directories."""


class DatasetPathNotFoundError(FileNotFoundError):
    """Raised when a resolved dataset path does not exist."""


_CUSTOM_ALLOWED_ROOTS: List[Path] = []


def register_allowed_root(root: Union[str, Path]) -> None:
    """Register an additional permitted root directory (e.g. for test fixtures)."""
    p = Path(root).resolve()
    if p not in _CUSTOM_ALLOWED_ROOTS:
        _CUSTOM_ALLOWED_ROOTS.append(p)


def unregister_allowed_root(root: Union[str, Path]) -> None:
    """Remove a previously registered permitted root directory."""
    p = Path(root).resolve()
    if p in _CUSTOM_ALLOWED_ROOTS:
        _CUSTOM_ALLOWED_ROOTS.remove(p)


def get_default_allowed_roots() -> List[Path]:
    """Returns the list of canonical permitted root directories."""
    roots: List[Path] = []

    # Configured dataset root from env
    env_root = os.environ.get("DATASET_ROOT") or os.environ.get("MASTERDB_DATASET_ROOT")
    if env_root:
        roots.append(Path(env_root).resolve())

    # Standard workspace roots
    roots.append((WORKSPACE_ROOT / "datasets").resolve())
    roots.append((WORKSPACE_ROOT / "upload_staging").resolve())
    roots.append((WORKSPACE_ROOT / "upload_store").resolve())
    roots.append((WORKSPACE_ROOT / "reports").resolve())
    roots.append((WORKSPACE_ROOT / "config").resolve())

    storage_root = os.environ.get("MASTERDB_STORAGE_DIR")
    if storage_root:
        roots.append(Path(storage_root).resolve())

    # Include any dynamically registered roots (e.g. pytest tmp_path)
    for r in _CUSTOM_ALLOWED_ROOTS:
        if r not in roots:
            roots.append(r)

    return roots


def resolve_secure_path(
    user_path: Union[str, Path],
    allowed_roots: Optional[Iterable[Union[str, Path]]] = None,
    allow_nonexistent: bool = False,
    default_root: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Resolve a user-provided or API-provided path and verify it stays inside permitted roots.

    Parameters:
    - user_path: The user-supplied path string or Path object.
    - allowed_roots: Optional explicit list of allowed roots. Defaults to get_default_allowed_roots().
    - allow_nonexistent: If False (default), verifies the file actually exists.
    - default_root: If user_path is relative, resolve it relative to default_root.

    Returns:
    - Canonical, resolved Path.

    Raises:
    - PathTraversalError: If the path attempts traversal or escapes permitted roots.
    - DatasetPathNotFoundError: If allow_nonexistent is False and the file does not exist.
    """
    if user_path is None:
        raise PathTraversalError("Path cannot be None.")

    path_str = str(user_path).strip()
    if not path_str:
        raise PathTraversalError("Path cannot be empty.")

    # Base candidate path
    p = Path(path_str)

    # Determine default root for relative paths
    if default_root is not None:
        base_dir = Path(default_root).resolve()
    else:
        env_root = os.environ.get("DATASET_ROOT") or os.environ.get("MASTERDB_DATASET_ROOT")
        base_dir = Path(env_root).resolve() if env_root else (WORKSPACE_ROOT / "datasets").resolve()

    if not p.is_absolute():
        candidate = (base_dir / p).resolve()
    else:
        candidate = p.resolve()

    # Determine allowed roots
    if allowed_roots is not None:
        roots = [Path(r).resolve() for r in allowed_roots]
    else:
        roots = get_default_allowed_roots()

    # Verify candidate is contained within at least one permitted root
    is_safe = False
    for root in roots:
        try:
            # candidate.is_relative_to(root)
            candidate.relative_to(root)
            is_safe = True
            break
        except ValueError:
            continue

    if not is_safe:
        raise PathTraversalError(
            f"Path traversal detected: '{path_str}' resolves outside permitted dataset directories."
        )

    if not allow_nonexistent and not candidate.exists():
        raise DatasetPathNotFoundError(f"Dataset path does not exist: '{path_str}'")

    return candidate
