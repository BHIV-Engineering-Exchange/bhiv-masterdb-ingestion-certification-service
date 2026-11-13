"""
Re-export module for MASTERDB-GEO-QUEST-01 reproduce_all.

Resolves namespace collision between root-level `scripts/` and
`MASTERDB-GEO-QUEST-01/scripts/` for static analysis tools and CLI execution.
"""
import importlib.util
import sys
from pathlib import Path

_GEO_QUEST_DIR = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01"
_TARGET_SCRIPT = _GEO_QUEST_DIR / "scripts" / "reproduce_all.py"

if str(_GEO_QUEST_DIR) not in sys.path:
    sys.path.insert(0, str(_GEO_QUEST_DIR))

if _TARGET_SCRIPT.is_file():
    _spec = importlib.util.spec_from_file_location("scripts.reproduce_all_source", _TARGET_SCRIPT)
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["scripts.reproduce_all_source"] = _module
        _spec.loader.exec_module(_module)

        for _attr_name, _attr_val in _module.__dict__.items():
            if not _attr_name.startswith("__"):
                globals()[_attr_name] = _attr_val

        if __name__ == "__main__":
            _main_fn = getattr(_module, "main", None)
            if callable(_main_fn):
                sys.exit(_main_fn())

