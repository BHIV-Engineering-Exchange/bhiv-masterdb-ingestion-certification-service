"""
Re-export module for MASTERDB-GEO-QUEST-01 clean_aircraft.

Resolves namespace collision between root-level `scripts/` and
`MASTERDB-GEO-QUEST-01/scripts/` for static analysis tools (Pylance, Pyright, mypy, IDEs)
and runtime imports.
"""
import importlib.util
import sys
from pathlib import Path

_GEO_QUEST_DIR = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01"
_CLEAN_AIRCRAFT_PATH = _GEO_QUEST_DIR / "scripts" / "clean_aircraft.py"

if str(_GEO_QUEST_DIR) not in sys.path:
    sys.path.insert(0, str(_GEO_QUEST_DIR))

if _CLEAN_AIRCRAFT_PATH.is_file():
    _spec = importlib.util.spec_from_file_location("scripts.clean_aircraft_source", _CLEAN_AIRCRAFT_PATH)
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["scripts.clean_aircraft_source"] = _module
        _spec.loader.exec_module(_module)

        # Explicit export for IDE autocomplete and static type analyzers
        clean_and_normalize_dataset = getattr(_module, "clean_and_normalize_dataset", None)

        for _attr_name, _attr_val in _module.__dict__.items():
            if not _attr_name.startswith("__"):
                globals()[_attr_name] = _attr_val

