import tempfile
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch

from change_detector import detect_changes
from csv_manager import CSVManager
from file_scanner import compute_checksum, scan_project_files
from models import TrackedFile


class ProjectFileManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="pfm_test_"))
        self.app_data = self.temp_dir / "app_data"
        self.app_data.mkdir()
        self.project_root = self.temp_dir / "sample_project"
        self.project_root.mkdir()
        self.csv_manager = CSVManager(base_dir=self.app_data)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_csv_manager_creates_expected_tables(self) -> None:
        self.assertTrue(self.csv_manager.paths["projects"].exists())
        self.assertTrue(self.csv_manager.paths["files"].exists())
        self.assertTrue(self.csv_manager.paths["change_log"].exists())
        self.assertTrue(self.csv_manager.paths["todos"].exists())
        project_headers = self.csv_manager.paths["projects"].read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("pinned", project_headers)

    def test_scan_project_files_and_detect_modify(self) -> None:
        test_file = self.project_root / "example.txt"
        test_file.write_text("hello world", encoding="utf-8")

        scanned = list(scan_project_files(self.project_root))
        self.assertEqual(len(scanned), 1)
        self.assertEqual(scanned[0]["relative_path"], "example.txt")

        tracked = TrackedFile(
            file_id="1",
            project_id="1",
            relative_path="example.txt",
            extension=".txt",
            file_size=test_file.stat().st_size,
            last_modified=scanned[0]["last_modified"],
            checksum=compute_checksum(test_file),
            notes="",
        )
        self.assertEqual(len(detect_changes("1", [tracked], scanned)), 0)

        test_file.write_text("hello world again", encoding="utf-8")
        scanned_updated = list(scan_project_files(self.project_root))
        changes = detect_changes("1", [tracked], scanned_updated)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "MODIFY")

    def test_manual_file_discovery(self) -> None:
        test_file = self.project_root / "manual.md"
        test_file.write_text("manual note", encoding="utf-8")
        scanned = list(scan_project_files(self.project_root))
        self.assertTrue(any(row["relative_path"] == "manual.md" for row in scanned))

    def test_migrates_legacy_csv_files_when_target_missing(self) -> None:
        legacy_home = self.temp_dir / "legacy_home"
        legacy_dir = legacy_home / ".project_doc_tracker"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "projects.csv").write_text(
            "project_id,project_name,root_path,description,tags,created_date,last_scanned_date\n"
            "1,Legacy Project,/tmp/legacy,,,2026-01-01T00:00:00,\n",
            encoding="utf-8",
        )

        new_data_dir = self.temp_dir / "new_data"
        new_data_dir.mkdir()

        with patch("csv_manager.Path.home", return_value=legacy_home):
            manager = CSVManager(base_dir=new_data_dir)

        rows = manager.read_rows("projects")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_name"], "Legacy Project")
        self.assertIn("pinned", rows[0])

    def test_does_not_overwrite_existing_csv_during_migration(self) -> None:
        legacy_home = self.temp_dir / "legacy_home_2"
        legacy_dir = legacy_home / ".project_doc_tracker"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "projects.csv").write_text(
            "project_id,project_name,root_path,description,tags,created_date,last_scanned_date\n"
            "1,Legacy Project,/tmp/legacy,,,2026-01-01T00:00:00,\n",
            encoding="utf-8",
        )

        new_data_dir = self.temp_dir / "existing_data"
        new_data_dir.mkdir()
        (new_data_dir / "projects.csv").write_text(
            "project_id,project_name,root_path,description,tags,created_date,last_scanned_date\n"
            "7,Current Project,/tmp/current,,,2026-02-02T00:00:00,\n",
            encoding="utf-8",
        )

        with patch("csv_manager.Path.home", return_value=legacy_home):
            manager = CSVManager(base_dir=new_data_dir)

        rows = manager.read_rows("projects")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["project_name"], "Current Project")


    def test_detect_changes_move(self) -> None:
        original_file = self.project_root / "old_name.txt"
        original_file.write_text("content", encoding="utf-8")
        checksum = compute_checksum(original_file)
        tracked = TrackedFile(
            file_id="1",
            project_id="1",
            relative_path="old_name.txt",
            extension=".txt",
            file_size=original_file.stat().st_size,
            last_modified="",
            checksum=checksum,
            notes="",
        )
        scanned = [{
            "relative_path": "new_name.txt",
            "extension": ".txt",
            "file_size": str(original_file.stat().st_size),
            "last_modified": "",
            "checksum": checksum,
        }]
        changes = detect_changes("1", [tracked], scanned)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "MOVE")
        self.assertEqual(changes[0].old_value, "old_name.txt")
        self.assertEqual(changes[0].new_value, "new_name.txt")

    def test_detect_changes_remove(self) -> None:
        tracked = TrackedFile(
            file_id="1",
            project_id="1",
            relative_path="deleted.txt",
            extension=".txt",
            file_size=0,
            last_modified="",
            checksum="abc123",
            notes="",
        )
        changes = detect_changes("1", [tracked], [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "REMOVE")
        self.assertEqual(changes[0].old_value, "deleted.txt")

if __name__ == "__main__":
    unittest.main()
