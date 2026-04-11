import csv
from pathlib import Path
from typing import Dict, List, Optional

PROJECTS_SCHEMA = [
    "project_id",
    "project_name",
    "root_path",
    "description",
    "tags",
    "created_date",
    "last_scanned_date",
]

FILES_SCHEMA = [
    "file_id",
    "project_id",
    "relative_path",
    "extension",
    "file_size",
    "last_modified",
    "checksum",
    "notes",
]

CHANGE_LOG_SCHEMA = [
    "timestamp",
    "project_id",
    "file_id",
    "change_type",
    "old_value",
    "new_value",
    "note",
]

TODO_SCHEMA = [
    "todo_id",
    "project_id",
    "description",
    "created_date",
]

class CSVManager:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        default_dir = Path(__file__).resolve().parent
        self.base_dir = (base_dir or default_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_from_legacy(Path.home() / ".project_doc_tracker")
        self.paths = {
            "projects": self.base_dir / "projects.csv",
            "files": self.base_dir / "files.csv",
            "change_log": self.base_dir / "change_log.csv",
            "todos": self.base_dir / "todos.csv",
        }
        self._ensure_csv("projects", PROJECTS_SCHEMA)
        self._ensure_csv("files", FILES_SCHEMA)
        self._ensure_csv("change_log", CHANGE_LOG_SCHEMA)
        self._ensure_csv("todos", TODO_SCHEMA)

    def _migrate_from_legacy(self, legacy_dir: Path) -> None:
        """Copy CSV files from the old ~/.project_doc_tracker location if the app
        folder does not yet have them."""
        if not legacy_dir.exists():
            return
        for filename in ("projects.csv", "files.csv", "change_log.csv", "todos.csv"):
            dest = self.base_dir / filename
            src = legacy_dir / filename
            if src.exists() and not dest.exists():
                import shutil
                shutil.copy2(src, dest)

    def _ensure_csv(self, name: str, headers: List[str]) -> None:
        path = self.paths[name]
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()

    def read_rows(self, name: str) -> List[Dict[str, str]]:
        path = self.paths[name]
        with path.open("r", newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            return [row for row in reader if any(row.values())]

    def append_row(self, name: str, row: Dict[str, str]) -> None:
        path = self.paths[name]
        headers = self._schema_for(name)
        with path.open("a", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writerow(row)

    def write_rows(self, name: str, rows: List[Dict[str, str]]) -> None:
        path = self.paths[name]
        headers = self._schema_for(name)
        with path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    def next_id(self, name: str, id_field: str) -> str:
        rows = self.read_rows(name)
        max_value = 0
        for row in rows:
            try:
                current = int(row.get(id_field, "0"))
                if current > max_value:
                    max_value = current
            except ValueError:
                continue
        return str(max_value + 1)

    def _schema_for(self, name: str) -> List[str]:
        if name == "projects":
            return PROJECTS_SCHEMA
        if name == "files":
            return FILES_SCHEMA
        if name == "change_log":
            return CHANGE_LOG_SCHEMA
        if name == "todos":
            return TODO_SCHEMA
        raise ValueError(f"Unknown CSV name: {name}")
