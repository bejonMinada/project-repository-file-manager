# Project File Manager

Project File Manager is a local desktop application for organizing project folders, tracking files, logging file changes, and keeping project notes.

All data is stored locally in CSV files inside the application folder. No cloud service or database is required.

## Features

- Auto-detects project folders inside the built-in `repository` directory on launch and during global refresh.
- Global `Refresh` scans the entire repository and updates all projects and tracked file records.
- Snapshot support for tracked files (used by compare/restore workflows).
- Diff view for text-readable files using previous snapshots.
- Restore previous snapshot for a selected tracked file.
- Tracks files with checksum-based change detection (`ADD`, `REMOVE`, `MODIFY`, `MOVE`, `META_UPDATE`).
- Lets you add both files and folders into a selected project.
- File browser supports folder navigation with double-click to enter and `Back` to go up one level.
- Breadcrumb path display for current folder level.
- Uses file-type icons (including a zipped-folder icon for compressed files).
- Lets you open, rename, and remove tracked files/folders.
- Recycle-bin behavior for removals (`recycle_bin/`) instead of immediate permanent deletion.
- Project pin/favorite support and bulk tag editing for multiple selected projects.
- Advanced file filtering: filename, extension, and note text.
- History filter by change type.
- Backup export/import via ZIP.
- Activity dashboard with totals and most active project.
- Keyboard shortcuts:
	- `Ctrl+F`: focus file search
	- `Ctrl+N`: add project
	- `F5`: global refresh
	- `Alt+Left`: back folder
- Shows project change history and supports viewing history as a text file.
- Supports per-project notes.
- Includes reset functionality with confirmation text for full local data cleanup.

## Project Structure

- `main.py`: application entry point.
- `ui.py`: Tkinter UI and user actions.
- `models.py`: dataclasses for `Project`, `TrackedFile`, and `ChangeRecord`.
- `csv_manager.py`: CSV creation/read/write helpers.
- `file_scanner.py`: recursive file scanning and checksum generation.
- `change_detector.py`: change comparison logic.
- `Project File Manager.bat`: Windows launcher with Python detection and venv bootstrapping.
- `repository/`: project folders tracked by the app.
- `projects.csv`, `files.csv`, `change_log.csv`, `todos.csv`: local data files.
- `snapshots/`: automatic file snapshots for compare/restore features.
- `recycle_bin/`: removed files/folders before permanent cleanup.

## Requirements

- Windows
- Python 3.10 or newer

## How to Run

1. Open the app folder.
2. Double-click `Project File Manager.bat`.

The launcher will:

1. Ensure the `repository` folder exists.
2. Find Python (from venv, PATH, or common install locations).
3. Create `.venv` if missing.
4. Install dependencies from `requirements.txt` (if any).
5. Start the application.

## First Use

1. Click `Add Project`.
2. Enter a project name, description, and tags.
3. Save to create the project folder under `repository`.
4. Select the project and use `Add Files` or `Add Folder`.
5. Use `Refresh` beside `Add Project` to globally rescan the repository.

## Main Actions

- `Add Project`: creates a new project folder and project record.
- `Refresh`: globally refreshes all repository projects and tracked files.
- `Toggle Pin`: pin or unpin a project.
- `Bulk Edit Tags`: apply tags to multiple selected projects.
- `Edit Details`: updates project name/description/tags and logs relevant changes.
- `View as Text File`: writes project history to a text file and opens it.
- `Compare with Previous Snapshot`: opens a diff against previous saved snapshot.
- `Restore Previous Snapshot`: rolls selected file back to a previous snapshot.
- `Remove File/Folder`: removes selected file/folder from disk and tracking.
- `Reset`: deletes all projects, tracked files, notes, and CSV records after confirmation.

## Data Files

The app stores data in these CSV files in the application folder:

- `projects.csv`
- `files.csv`
- `change_log.csv`
- `todos.csv`

If legacy CSV files exist from an older location, they are migrated automatically on startup.

## Running Tests

Use Python unittest:

```bash
python -m unittest test_app.py
```
