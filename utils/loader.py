import json
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import pandas as pd

from security.path_resolution import resolve_secure_path


class DatasetLoader:
    @staticmethod
    def load_dataset(
        path: Union[str, Path],
        allowed_roots: Optional[Iterable[Union[str, Path]]] = None,
    ) -> pd.DataFrame:
        resolved = resolve_secure_path(path, allowed_roots=allowed_roots)
        suffix = resolved.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(resolved)
        if suffix in [".xlsx", ".xls"]:
            return pd.read_excel(resolved)
        if suffix == ".json":
            return pd.read_json(resolved)
        raise ValueError(f"Unsupported format: {suffix}")

    @staticmethod
    def load_json(
        path: Union[str, Path],
        allowed_roots: Optional[Iterable[Union[str, Path]]] = None,
    ) -> Any:
        resolved = resolve_secure_path(path, allowed_roots=allowed_roots)
        with resolved.open("r", encoding="utf-8") as f:
            return json.load(f)
