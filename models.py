import getpass
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

@dataclass
class Project:
    project_id: str
    project_name: str
    root_path: str
    description: str = ""
    tags: str = ""
    pinned: str = "0"
    created_date: str = field(default_factory=lambda: datetime.now().isoformat())
    last_scanned_date: str = ""

    @classmethod
    def from_dict(cls, row: Dict[str, str]) -> "Project":
        return cls(
            project_id=row.get("project_id", ""),
            project_name=row.get("project_name", ""),
            root_path=row.get("root_path", ""),
            description=row.get("description", ""),
            tags=row.get("tags", ""),
            pinned=row.get("pinned", "0"),
            created_date=row.get("created_date", ""),
            last_scanned_date=row.get("last_scanned_date", ""),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "root_path": self.root_path,
            "description": self.description,
            "tags": self.tags,
            "pinned": self.pinned,
            "created_date": self.created_date,
            "last_scanned_date": self.last_scanned_date,
        }

@dataclass
class TrackedFile:
    file_id: str
    project_id: str
    relative_path: str
    extension: str
    file_size: int
    last_modified: str
    checksum: str
    notes: str = ""
    note_author: str = ""
    added_by: str = ""
    last_modified_by: str = ""

    @classmethod
    def from_dict(cls, row: Dict[str, str]) -> "TrackedFile":
        return cls(
            file_id=row.get("file_id", ""),
            project_id=row.get("project_id", ""),
            relative_path=row.get("relative_path", ""),
            extension=row.get("extension", ""),
            file_size=int(row.get("file_size", "0")),
            last_modified=row.get("last_modified", ""),
            checksum=row.get("checksum", ""),
            notes=row.get("notes", ""),
            note_author=row.get("note_author", ""),
            added_by=row.get("added_by", ""),
            last_modified_by=row.get("last_modified_by", ""),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "file_id": self.file_id,
            "project_id": self.project_id,
            "relative_path": self.relative_path,
            "extension": self.extension,
            "file_size": str(self.file_size),
            "last_modified": self.last_modified,
            "checksum": self.checksum,
            "notes": self.notes,
            "note_author": self.note_author,
            "added_by": self.added_by,
            "last_modified_by": self.last_modified_by,
        }

@dataclass
class ChangeRecord:
    timestamp: str
    project_id: str
    file_id: str
    change_type: str
    old_value: str
    new_value: str
    note: str = ""
    username: str = field(default_factory=getpass.getuser)

    def to_dict(self) -> Dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "project_id": self.project_id,
            "file_id": self.file_id,
            "change_type": self.change_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "note": self.note,
            "username": self.username,
        }
