#!/usr/bin/env python3
"""
BHIV vNEXT MASTERDB-GEO-QUEST-01: End-to-End Pipeline Reproduction Script
Executes profiling, deterministic cleaning, quality gate validation,
negative failure scenario execution, and registration/retrieval reconciliation from a clean state.
"""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def main():
    print("=" * 75)
    print("BHIV vNEXT MASTERDB-GEO-QUEST-01: FULL REPRODUCIBLE RE-RUN")
    print("Author: Hariom Upadhyay | Reviewer: Harsha Pawar")
    print(f"Project Directory: {PROJECT_ROOT}")
    print("=" * 75)

    py_exe = sys.executable

    steps = [
        ("Step 1: Dataset Profiling", [py_exe, str(PROJECT_ROOT / "scripts" / "profile_aircraft.py")]),
        ("Step 2: Cleaning & Schema Normalization", [py_exe, str(PROJECT_ROOT / "scripts" / "clean_aircraft.py")]),
        ("Step 3: Quality Gate Validation", [py_exe, str(PROJECT_ROOT / "scripts" / "validate_aircraft.py")]),
        ("Step 4: Failure Scenarios & Exception Register", [py_exe, str(PROJECT_ROOT / "scripts" / "run_failure_scenarios.py")]),
        ("Step 5: Registration & Retrieval Reconciliation", [py_exe, str(PROJECT_ROOT / "scripts" / "reconcile_registration.py")]),
    ]

    for title, cmd in steps:
        print(f"\n>>> Running {title}...")
        res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
        if res.returncode != 0:
            print(f"[ERROR] {title} failed with exit code {res.returncode}")
            sys.exit(res.returncode)

    print("\n" + "=" * 75)
    print("[SUCCESS] All 5 pipeline stages executed cleanly and verified.")
    print("=" * 75)

if __name__ == "__main__":
    main()
