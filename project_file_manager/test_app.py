import tempfile
import unittest
from pathlib import Path

from csv_manager import CSVManager
from file_scanner import scan_project_files, compute_checksum
from change_detector import detect_changes
from models import Project, TrackedFile


class ProjectDocTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="project_doc_test_"))
        self.app_data = self.temp_dir / "app_data"
        self.app_data.mkdir()
        self.project_root = self.temp_dir / "project_root"
        self.project_root.mkdir()
        self.csv_manager = CSVManager(base_dir=self.app_data)

    def tearDown(self) -> None:
        # Remove the temp directory tree
        for child in self.temp_dir.glob("**/*"):
            try:
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            except Exception:
                pass
        try:
            self.temp_dir.rmdir()
        except Exception:
            pass

    def test_csv_manager_creates_files(self) -> None:
        self.assertTrue(self.csv_manager.paths["projects"].exists())
        self.assertTrue(self.csv_manager.paths["files"].exists())
        self.assertTrue(self.csv_manager.paths["change_log"].exists())

    def test_scan_project_files_and_track(self) -> None:
        test_file = self.project_root / "example.txt"
        test_file.write_text("hello world", encoding="utf-8")
        scanned = list(scan_project_files(self.project_root))
        self.assertEqual(len(scanned), 1)
        self.assertEqual(scanned[0]["relative_path"], "example.txt")
        checksum = compute_checksum(test_file)
        tracked = TrackedFile(
            file_id="1",
            project_id="1",
            relative_path="example.txt",
            extension=".txt",
            file_size=test_file.stat().st_size,
            last_modified=scanned[0]["last_modified"],
            checksum=checksum,
            notes="",
        )
        changes = detect_changes("1", [tracked], scanned)
        self.assertEqual(len(changes), 0)
        test_file.write_text("hello world again", encoding="utf-8")
        scanned_updated = list(scan_project_files(self.project_root))
        changes_updated = detect_changes("1", [tracked], scanned_updated)
        self.assertEqual(len(changes_updated), 1)
        self.assertEqual(changes_updated[0].change_type, "MODIFY")

    def test_manual_file_discovery(self) -> None:
        test_file = self.project_root / "manual.md"
        test_file.write_text("manual add", encoding="utf-8")
        scanned = list(scan_project_files(self.project_root))
        self.assertTrue(any(row["relative_path"] == "manual.md" for row in scanned))


if __name__ == "__main__":
    unittest.main()
