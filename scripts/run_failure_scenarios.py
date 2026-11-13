"""Re-export module for MASTERDB-GEO-QUEST-01 run_failure_scenarios."""
import importlib.util, sys
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01" / "scripts" / "run_failure_scenarios.py"
if _P.is_file():
    _spec = importlib.util.spec_from_file_location("scripts.run_failure_scenarios_src", _P)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["scripts.run_failure_scenarios_src"] = _mod
        _spec.loader.exec_module(_mod)
        for _k, _v in _mod.__dict__.items():
            if not _k.startswith("__"):
                globals()[_k] = _v

