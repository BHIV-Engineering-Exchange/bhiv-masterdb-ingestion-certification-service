"""
Re-export module for MASTERDB-GEO-QUEST-01 rule evaluator.

Resolves namespace collision between root-level `scripts/` and
`MASTERDB-GEO-QUEST-01/scripts/` for static analysis tools (Pylance, Pyright, mypy, IDEs)
and runtime imports.
"""
import importlib.util
import sys
from pathlib import Path

_GEO_QUEST_DIR = Path(__file__).resolve().parent.parent / "MASTERDB-GEO-QUEST-01"
_RULE_EVALUATOR_PATH = _GEO_QUEST_DIR / "scripts" / "rule_evaluator.py"

if str(_GEO_QUEST_DIR) not in sys.path:
    sys.path.insert(0, str(_GEO_QUEST_DIR))

if _RULE_EVALUATOR_PATH.is_file():
    _spec = importlib.util.spec_from_file_location("scripts.rule_evaluator_source", _RULE_EVALUATOR_PATH)
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["scripts.rule_evaluator_source"] = _module
        _spec.loader.exec_module(_module)

        # Explicit exports for IDE autocomplete and static type analyzers
        evaluate_batch = getattr(_module, "evaluate_batch", None)
        evaluate_record = getattr(_module, "evaluate_record", None)
        evaluate_dataset = getattr(_module, "evaluate_dataset", None)

        for _attr_name, _attr_val in _module.__dict__.items():
            if not _attr_name.startswith("__"):
                globals()[_attr_name] = _attr_val
