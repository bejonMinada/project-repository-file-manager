from datetime import datetime
from pathlib import Path
from typing import Dict, List

from models import ChangeRecord, TrackedFile


def _build_index(old_files: List[TrackedFile]) -> Dict[str, TrackedFile]:
    return {file.relative_path: file for file in old_files}


def _checksum_index(old_files: List[TrackedFile]) -> Dict[str, TrackedFile]:
    return {file.checksum: file for file in old_files}


def detect_changes(
    project_id: str,
    old_files: List[TrackedFile],
    scanned_rows: List[Dict[str, str]],
) -> List[ChangeRecord]:
    old_index = _build_index(old_files)
    checksum_index = _checksum_index(old_files)
    current_index: Dict[str, Dict[str, str]] = {row["relative_path"]: row for row in scanned_rows}
    records: List[ChangeRecord] = []
    now = datetime.now().isoformat()

    for rel_path, current in current_index.items():
        old = old_index.get(rel_path)
        if old is None:
            moved = checksum_index.get(current["checksum"])
            if moved:
                records.append(
                    ChangeRecord(
                        timestamp=now,
                        project_id=project_id,
                        file_id=moved.file_id,
                        change_type="MOVE",
                        old_value=moved.relative_path,
                        new_value=rel_path,
                        note="Detected file moved by checksum match.",
                    )
                )
            else:
                records.append(
                    ChangeRecord(
                        timestamp=now,
                        project_id=project_id,
                        file_id="",
                        change_type="ADD",
                        old_value="",
                        new_value=rel_path,
                        note="New file discovered in project folder.",
                    )
                )
        else:
            if old.checksum != current["checksum"]:
                records.append(
                    ChangeRecord(
                        timestamp=now,
                        project_id=project_id,
                        file_id=old.file_id,
                        change_type="MODIFY",
                        old_value=old.checksum,
                        new_value=current["checksum"],
                        note="Checksum changed for tracked file.",
                    )
                )
            elif old.last_modified != current["last_modified"] or old.file_size != int(current["file_size"]):
                records.append(
                    ChangeRecord(
                        timestamp=now,
                        project_id=project_id,
                        file_id=old.file_id,
                        change_type="META_UPDATE",
                        old_value=f"size={old.file_size}, modified={old.last_modified}",
                        new_value=f"size={current['file_size']}, modified={current['last_modified']}",
                        note="File metadata updated without checksum change.",
                    )
                )

    current_checksum_index: Dict[str, Dict[str, str]] = {row["checksum"]: row for row in scanned_rows}
    for old in old_files:
        if old.relative_path not in current_index:
            if old.checksum not in current_checksum_index:
                records.append(
                    ChangeRecord(
                        timestamp=now,
                        project_id=project_id,
                        file_id=old.file_id,
                        change_type="REMOVE",
                        old_value=old.relative_path,
                        new_value="",
                        note="Previously tracked file is missing from the project folder.",
                    )
                )

    return records
