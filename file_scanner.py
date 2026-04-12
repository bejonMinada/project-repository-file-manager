import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, Optional


def compute_checksum(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def scan_project_files(root_path: Path, extensions: Optional[set[str]] = None) -> Iterator[Dict[str, str]]:
    root_path = root_path.resolve()
    for path in root_path.rglob("*"):
        if path.is_file():
            if extensions and path.suffix.lower() not in extensions:
                continue
            stat = path.stat()
            relative = path.relative_to(root_path)
            yield {
                "relative_path": str(relative).replace("\\", "/"),
                "extension": path.suffix.lower(),
                "file_size": str(stat.st_size),
                "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "checksum": compute_checksum(path),
            }
