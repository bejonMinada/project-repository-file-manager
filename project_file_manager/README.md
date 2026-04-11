# Personal Project Documentation Tracker

A minimal local desktop application in Python for personal project documentation, file tracking, and change history logging.

## Architecture

- `models.py`
  - `Project`, `TrackedFile`, and `ChangeRecord` data classes.
  - Responsible for typed object representation and CSV serialization.

- `csv_manager.py`
  - `CSVManager` abstraction for safe CSV creation, reads, writes, and append-only logging.
  - Stores files under `~/.project_doc_tracker` by default.

- `file_scanner.py`
  - Scans project root folders.
  - Computes SHA-256 checksums and captures file metadata.

- `change_detector.py`
  - Compares tracked files and current scanned file state.
  - Detects `ADD`, `REMOVE`, `MODIFY`, `MOVE`, and `META_UPDATE` events.

- `ui.py`
  - `DocumentTrackerApp` provides a simple Tkinter desktop interface.
  - Left pane: projects.
  - Center pane: tracked files and filters.
  - Right pane: selected file details and change history.

- `main.py`
  - Application entry point.

## Design decisions

- `tkinter` was chosen because it is part of the Python standard library, cross-platform, and avoids extra dependencies.
- CSV storage is the only persistence mechanism, satisfying the offline, local-only requirement.
- The app uses a built-in repository folder inside the app folder for project roots.
- The design keeps business logic separate from the UI so scanning and change detection can run independently of the GUI.

## CSV Schema Examples

### `projects.csv`

```
project_id,project_name,root_path,description,tags,created_date,last_scanned_date
1,Documentation Tracker,C:/Projects/DocTracker,Personal tracker project,tool,2026-04-11T10:00:00,
```

### `files.csv`

```
file_id,project_id,relative_path,extension,file_size,last_modified,checksum,notes
1,1,README.md,.md,1245,2026-04-11T10:05:00,3b5d5c3712955042212316173ccf37be,Initial file registration
```

### `change_log.csv`

```
timestamp,project_id,file_id,change_type,old_value,new_value,note
2026-04-11T10:10:00,1,1,MODIFY,oldchecksum,newchecksum,Detected checksum change
```

## Running the app

1. Open a terminal.
2. Change directory to the project folder:
   ```bash
   cd C:\Users\zbq74c\project_file_manager
   ```
3. Use the new launcher file:
   ```bash
   "Project File Manager.bat"
   ```
   This launcher will create a local virtual environment if needed, install any required Python packages from `requirements.txt`, and then start the app.
4. The app uses a built-in repository folder located in the application folder for project storage.

## Notes

- The `Add Files` button copies selected files into the project folder and tracks them automatically.
- The app now discovers manually added files when you refresh or select a project, logs them as manually discovered additions, and stores them in `files.csv`.
- The UI supports `Open File` to launch files, `Rename File` to rename tracked files inside the project, and `Delete File` to remove one or more selected files from disk and tracking.
- `Delete Project Folder` removes the project from tracking and deletes the folder on disk.
- `Remove Project` removes the project from the panel and tracking without deleting the folder.
- Search supports partial substring lookups so typing a few characters will match file names and project tags/folder names.
- Extension filtering uses a dropdown of available tracked extensions.
- It is designed for personal, offline use only.
- No database or cloud services are required.
