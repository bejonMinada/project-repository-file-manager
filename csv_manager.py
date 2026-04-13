import base64
import csv
import hashlib
import hmac
import io
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

PROJECTS_SCHEMA = [
    "project_id",
    "project_name",
    "root_path",
    "description",
    "tags",
    "pinned",
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
    "title",
    "description",
    "created_date",
]

ITEM_INVENTORY_SCHEMA = [
    "project_id",
    "item_id",
    "relative_path",
    "extension",
    "checksum",
    "last_seen",
]

class CSVManager:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        default_dir = Path(__file__).resolve().parent
        self.base_dir = (base_dir or default_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._magic = "PRFM_ENC_V1:"
        self._key_path = self.base_dir / ".prfm_data_key"
        self._encryption_key = self._load_or_create_key()
        self._migrate_from_legacy(Path.home() / ".project_doc_tracker")
        self.paths = {
            "projects": self.base_dir / "projects.csv",
            "files": self.base_dir / "files.csv",
            "change_log": self.base_dir / "change_log.csv",
            "todos": self.base_dir / "todos.csv",
            "item_inventory": self.base_dir / "item_inventory.csv",
        }
        self._ensure_csv("projects", PROJECTS_SCHEMA)
        self._ensure_csv("files", FILES_SCHEMA)
        self._ensure_csv("change_log", CHANGE_LOG_SCHEMA)
        self._ensure_csv("todos", TODO_SCHEMA)
        self._ensure_csv("item_inventory", ITEM_INVENTORY_SCHEMA)

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            raw = self._key_path.read_text(encoding="utf-8").strip()
            if raw:
                return base64.urlsafe_b64decode(raw.encode("ascii"))
        key = os.urandom(32)
        self._key_path.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")
        return key

    def _xor_stream(self, data: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(data):
            block = hashlib.sha256(self._encryption_key + nonce + counter.to_bytes(8, "big")).digest()
            output.extend(block)
            counter += 1
        return bytes(a ^ b for a, b in zip(data, output[: len(data)]))

    def _encrypt_text(self, text: str) -> str:
        nonce = os.urandom(16)
        plain = text.encode("utf-8")
        cipher = self._xor_stream(plain, nonce)
        tag = hmac.new(self._encryption_key, nonce + cipher, hashlib.sha256).digest()
        payload = base64.b64encode(nonce + tag + cipher).decode("ascii")
        return f"{self._magic}{payload}"

    def _decrypt_text(self, content: str) -> tuple[str, bool]:
        if not content.startswith(self._magic):
            return content, False
        payload = base64.b64decode(content[len(self._magic) :].encode("ascii"))
        if len(payload) < 48:
            raise ValueError("Encrypted payload is too short.")
        nonce = payload[:16]
        tag = payload[16:48]
        cipher = payload[48:]
        expected = hmac.new(self._encryption_key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Integrity check failed for encrypted data.")
        plain = self._xor_stream(cipher, nonce)
        return plain.decode("utf-8"), True

    def _read_csv_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        raw = path.read_text(encoding="utf-8")
        try:
            plain, _ = self._decrypt_text(raw)
            return plain
        except Exception:
            backup = path.with_suffix(path.suffix + ".bak")
            if backup.exists():
                backup_raw = backup.read_text(encoding="utf-8")
                backup_plain, _ = self._decrypt_text(backup_raw)
                path.write_text(backup_raw, encoding="utf-8")
                return backup_plain
            raise

    def _write_csv_text(self, path: Path, text: str) -> None:
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup)
        encrypted = self._encrypt_text(text)
        path.write_text(encrypted, encoding="utf-8")

    def _parse_csv_rows(self, text: str) -> tuple[List[str], List[Dict[str, str]]]:
        if not text.strip():
            return [], []
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        rows = [row for row in reader if any(row.values())]
        return headers, rows

    def _serialize_csv_rows(self, headers: List[str], rows: List[Dict[str, str]]) -> str:
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue()

    def _migrate_from_legacy(self, legacy_dir: Path) -> None:
        """Copy CSV files from the old ~/.project_doc_tracker location if the app
        folder does not yet have them."""
        if not legacy_dir.exists():
            return
        for filename in ("projects.csv", "files.csv", "change_log.csv", "todos.csv", "item_inventory.csv"):
            dest = self.base_dir / filename
            src = legacy_dir / filename
            if src.exists() and not dest.exists():
                shutil.copy2(src, dest)

    def _ensure_csv(self, name: str, headers: List[str]) -> None:
        path = self.paths[name]
        if not path.exists():
            self._write_csv_text(path, self._serialize_csv_rows(headers, []))
            return

        # Upgrade existing CSV files when schema gains new columns.
        csv_text = self._read_csv_text(path)
        current_headers, rows = self._parse_csv_rows(csv_text)

        if current_headers == headers:
            # Normalize file to encrypted form even if it was plain text before.
            self._write_csv_text(path, self._serialize_csv_rows(headers, rows))
            return

        normalized_rows: List[Dict[str, str]] = []
        for row in rows:
            normalized = {header: row.get(header, "") for header in headers}
            normalized_rows.append(normalized)

        self._write_csv_text(path, self._serialize_csv_rows(headers, normalized_rows))

    def read_rows(self, name: str) -> List[Dict[str, str]]:
        path = self.paths[name]
        csv_text = self._read_csv_text(path)
        _headers, rows = self._parse_csv_rows(csv_text)
        return rows

    def append_row(self, name: str, row: Dict[str, str]) -> None:
        rows = self.read_rows(name)
        rows.append({header: row.get(header, "") for header in self._schema_for(name)})
        self.write_rows(name, rows)

    def write_rows(self, name: str, rows: List[Dict[str, str]]) -> None:
        path = self.paths[name]
        headers = self._schema_for(name)
        normalized_rows = [{header: row.get(header, "") for header in headers} for row in rows]
        self._write_csv_text(path, self._serialize_csv_rows(headers, normalized_rows))

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
        if name == "item_inventory":
            return ITEM_INVENTORY_SCHEMA
        raise ValueError(f"Unknown CSV name: {name}")
