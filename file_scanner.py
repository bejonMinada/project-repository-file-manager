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
    yield from scan_project_files_with_cache(root_path, checksum_cache={}, extensions=extensions)


def scan_project_files_with_cache(
    root_path: Path,
    checksum_cache: Dict[str, tuple[str, str, str]],
    extensions: Optional[set[str]] = None,
) -> Iterator[Dict[str, str]]:
    """Scan project files while reusing checksums for unchanged files.

    checksum_cache maps relative_path -> (file_size, last_modified, checksum).
    """
    root_path = root_path.resolve()
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        if extensions and path.suffix.lower() not in extensions:
            continue

        try:
            stat = path.stat()
        except OSError:
            continue
        relative = path.relative_to(root_path)
        relative_path = str(relative).replace("\\", "/")
        file_size = str(stat.st_size)
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()

        cached = checksum_cache.get(relative_path)
        if cached and cached[0] == file_size and cached[1] == last_modified:
            checksum = cached[2]
        else:
            try:
                checksum = compute_checksum(path)
            except PermissionError:
                checksum = cached[2] if cached else ""
            except OSError:
                checksum = cached[2] if cached else ""

        yield {
            "relative_path": relative_path,
            "extension": path.suffix.lower(),
            "file_size": file_size,
            "last_modified": last_modified,
            "checksum": checksum,
        }
