import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import launch_app
from change_detector import detect_changes
from csv_manager import CSVManager
from file_scanner import compute_checksum, scan_project_files
from launch_app import (
    check_python_version,
    create_virtualenv,
    ensure_runtime_folders,
    install_requirements,
    read_requirements,
    run_application,
)
from models import ChangeRecord, Project, TrackedFile


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

    def test_models_roundtrip(self) -> None:
        project = Project(
            project_id="1",
            project_name="Demo",
            root_path="/tmp/demo",
            description="desc",
            tags="a,b",
            pinned="1",
            created_date="2026-01-01T00:00:00",
            last_scanned_date="2026-01-01T01:00:00",
        )
        project_loaded = Project.from_dict(project.to_dict())
        self.assertEqual(project_loaded.project_name, "Demo")
        self.assertEqual(project_loaded.pinned, "1")

        tracked = TrackedFile(
            file_id="10",
            project_id="1",
            relative_path="docs/readme.txt",
            extension=".txt",
            file_size=12,
            last_modified="2026-01-01T00:00:00",
            checksum="abc",
            notes="note",
        )
        tracked_loaded = TrackedFile.from_dict(tracked.to_dict())
        self.assertEqual(tracked_loaded.file_size, 12)
        self.assertEqual(tracked_loaded.notes, "note")

        record = ChangeRecord(
            timestamp="2026-01-01T00:00:00",
            project_id="1",
            file_id="10",
            change_type="ADD",
            old_value="",
            new_value="docs/readme.txt",
            note="created",
        )
        self.assertEqual(record.to_dict()["change_type"], "ADD")

    def test_csv_manager_creates_expected_tables(self) -> None:
        self.assertTrue(self.csv_manager.paths["projects"].exists())
        self.assertTrue(self.csv_manager.paths["files"].exists())
        self.assertTrue(self.csv_manager.paths["change_log"].exists())
        self.assertTrue(self.csv_manager.paths["todos"].exists())
        project_headers = self.csv_manager.paths["projects"].read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("pinned", project_headers)

    def test_csv_manager_append_write_read_and_next_id(self) -> None:
        row1 = {
            "project_id": "1",
            "project_name": "One",
            "root_path": "C:/repo/one",
            "description": "",
            "tags": "",
            "pinned": "0",
            "created_date": "",
            "last_scanned_date": "",
        }
        row2 = {
            "project_id": "2",
            "project_name": "Two",
            "root_path": "C:/repo/two",
            "description": "",
            "tags": "",
            "pinned": "1",
            "created_date": "",
            "last_scanned_date": "",
        }
        self.csv_manager.append_row("projects", row1)
        self.csv_manager.append_row("projects", row2)

        rows = self.csv_manager.read_rows("projects")
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.csv_manager.next_id("projects", "project_id"), "3")

        self.csv_manager.write_rows("projects", [row2])
        rows_after = self.csv_manager.read_rows("projects")
        self.assertEqual(len(rows_after), 1)
        self.assertEqual(rows_after[0]["project_name"], "Two")

    def test_csv_manager_upgrades_schema_with_new_columns(self) -> None:
        legacy_projects = self.app_data / "legacy_projects.csv"
        legacy_projects.write_text(
            "project_id,project_name,root_path,description,tags,created_date,last_scanned_date\n"
            "1,Legacy,/tmp/legacy,,,,\n",
            encoding="utf-8",
        )
        target = self.app_data / "projects.csv"
        shutil.copy2(legacy_projects, target)

        manager = CSVManager(base_dir=self.app_data)
        rows = manager.read_rows("projects")
        self.assertEqual(rows[0]["project_name"], "Legacy")
        self.assertIn("pinned", rows[0])

    def test_scan_project_files_extension_filter_and_path_normalization(self) -> None:
        nested = self.project_root / "folder"
        nested.mkdir()
        file_txt = nested / "note.txt"
        file_py = nested / "script.py"
        file_txt.write_text("hello", encoding="utf-8")
        file_py.write_text("print('ok')", encoding="utf-8")

        scanned_txt = list(scan_project_files(self.project_root, extensions={".txt"}))
        self.assertEqual(len(scanned_txt), 1)
        self.assertEqual(scanned_txt[0]["relative_path"], "folder/note.txt")

        scanned_all = list(scan_project_files(self.project_root))
        self.assertEqual(len(scanned_all), 2)
        self.assertTrue(any(item["relative_path"] == "folder/script.py" for item in scanned_all))

    def test_compute_checksum_changes_with_content(self) -> None:
        sample = self.project_root / "checksum.txt"
        sample.write_text("first", encoding="utf-8")
        first = compute_checksum(sample)
        sample.write_text("second", encoding="utf-8")
        second = compute_checksum(sample)
        self.assertNotEqual(first, second)

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

    def test_detect_changes_add_move_remove_meta_update_and_copy(self) -> None:
        old = TrackedFile(
            file_id="1",
            project_id="1",
            relative_path="old_name.txt",
            extension=".txt",
            file_size=7,
            last_modified="2026-01-01T00:00:00",
            checksum="same-checksum",
            notes="",
        )

        move_scan = [{
            "relative_path": "new_name.txt",
            "extension": ".txt",
            "file_size": "7",
            "last_modified": "2026-01-02T00:00:00",
            "checksum": "same-checksum",
        }]
        move_changes = detect_changes("1", [old], move_scan)
        self.assertEqual(len(move_changes), 1)
        self.assertEqual(move_changes[0].change_type, "MOVE")

        remove_changes = detect_changes("1", [old], [])
        self.assertEqual(len(remove_changes), 1)
        self.assertEqual(remove_changes[0].change_type, "REMOVE")

        add_changes = detect_changes("1", [], move_scan)
        self.assertEqual(len(add_changes), 1)
        self.assertEqual(add_changes[0].change_type, "ADD")

        copy_scan = [
            {
                "relative_path": "old_name.txt",
                "extension": ".txt",
                "file_size": "7",
                "last_modified": "2026-01-01T00:00:00",
                "checksum": "same-checksum",
            },
            {
                "relative_path": "copy.txt",
                "extension": ".txt",
                "file_size": "7",
                "last_modified": "2026-01-02T00:00:00",
                "checksum": "same-checksum",
            },
        ]
        copy_changes = detect_changes("1", [old], copy_scan)
        self.assertEqual(len(copy_changes), 1)
        self.assertEqual(copy_changes[0].change_type, "ADD")

        meta_scan = [{
            "relative_path": "old_name.txt",
            "extension": ".txt",
            "file_size": "9",
            "last_modified": "2026-01-02T00:00:00",
            "checksum": "same-checksum",
        }]
        meta_changes = detect_changes("1", [old], meta_scan)
        self.assertEqual(len(meta_changes), 1)
        self.assertEqual(meta_changes[0].change_type, "META_UPDATE")

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

    def test_read_requirements_ignores_comments_and_blank_lines(self) -> None:
        requirements_file = self.temp_dir / "requirements.txt"
        requirements_file.write_text(
            "# comment\n\nrequests==2.32.3\n  \n# another\npytest==8.3.5\n",
            encoding="utf-8",
        )

        with patch("launch_app.REQUIREMENTS_FILE", requirements_file):
            requirements = read_requirements()

        self.assertEqual(requirements, ["requests==2.32.3", "pytest==8.3.5"])

    def test_check_python_version_raises_when_too_low(self) -> None:
        with patch.object(launch_app, "MIN_PYTHON_VERSION", (99, 0)):
            with self.assertRaises(SystemExit):
                check_python_version()

    def test_create_virtualenv_returns_python_path(self) -> None:
        fake_env_dir = self.temp_dir / "venv_test"

        class FakeBuilder:
            def __init__(self, with_pip: bool) -> None:
                self.with_pip = with_pip

            def create(self, path: Path) -> None:
                scripts = path / "Scripts"
                scripts.mkdir(parents=True, exist_ok=True)
                (scripts / "python.exe").write_text("", encoding="utf-8")

        with patch.object(launch_app, "VENV_DIR", fake_env_dir), patch("launch_app.venv.EnvBuilder", FakeBuilder):
            python_exe = create_virtualenv()

        self.assertTrue(python_exe.exists())
        self.assertTrue(str(python_exe).endswith("python.exe"))

    def test_install_requirements_runs_pip_commands(self) -> None:
        python_exe = Path("C:/fake/python.exe")
        with patch("launch_app.read_requirements", return_value=["requests==2.32.3"]), patch("launch_app.subprocess.run") as mocked_run:
            install_requirements(python_exe)

        self.assertEqual(mocked_run.call_count, 2)

    def test_run_application_returns_exit_code(self) -> None:
        with patch("launch_app.subprocess.run", return_value=SimpleNamespace(returncode=7)):
            self.assertEqual(run_application(Path("C:/fake/python.exe")), 7)

    def test_ensure_runtime_folders_creates_all_required_folders(self) -> None:
        custom_root = self.temp_dir / "launcher_root"
        custom_root.mkdir(parents=True, exist_ok=True)

        with patch.object(launch_app, "PROJECT_ROOT", custom_root):
            ensure_runtime_folders()

        self.assertTrue((custom_root / "repository").is_dir())
        self.assertTrue((custom_root / "snapshots").is_dir())
        self.assertTrue((custom_root / "recycle_bin").is_dir())


if __name__ == "__main__":
    unittest.main()
