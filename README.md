# Project Repository File Manager 3.0

Project Repository File Manager is a local desktop application for organizing project folders, tracking files, comparing revisions, restoring snapshots, and keeping project notes in a responsive Tkinter workspace.

All data is stored locally in CSV files inside the application folder. No cloud service, external database, or internet connection is required for normal use.

## About Dialog Description

Project Repository File Manager is shown in-app as a local desktop application for organizing project folders, tracking file changes, comparing revisions, restoring snapshots, and managing project notes in a responsive workspace. All data stays on the device with no cloud dependency.

## Features

- Auto-detects project folders inside the built-in `repository` directory on launch and during global refresh.
- Repository path is configurable from `Settings`, including OneDrive-synced SharePoint folders.
- Global `Refresh` scans the entire repository and updates all projects and tracked file records.
- Snapshot support for tracked files (used by compare/restore workflows).
- Diff view for text-readable files using previous snapshots, with metadata fallback for non-text files.
- Restore previous revision for a selected tracked file.
- Tracks files with checksum-based change detection (`ADD`, `REMOVE`, `MODIFY`, `MOVE`, `META_UPDATE`).
- Lets you add both files and folders into a selected project.
- File browser supports folder navigation with double-click to enter and `Back` to go up one level.
- Breadcrumb path display for current folder level.
- Uses file-type icons (including a zipped-folder icon for compressed files).
- Lets you open, rename, and remove tracked files/folders.
- Recycle-bin behavior for removals (`recycle_bin/`) instead of immediate permanent deletion.
- Project pin/favorite support and per-project tag editing.
- File browser supports queued `Copy File` and `Move File` actions, then `Copy Here` or `Move Here` on white-space in the destination folder view.
- Advanced file filtering: filename, extension, and note text.
- History filter by change type.
- Session capture/restore via ZIP (`Capture Session` / `Restore Session`) with default save/open path in backup `Session/`.
- Auto-generated backup workspace folders: `Backups/` and `Session/`.
- Restore project from auto-backup by selecting a timestamped backup folder.
- Recycle-bin restore is project-scoped to prevent cross-project file mixing.
- File context menu tools: `Extract Selected Archives Here`, `Compress Selected to ZIP`, and `Compress Folder to ZIP`.
- Activity dashboard with totals and most active project.
- Responsive right-side panel with scrollable Details, History, and Project Notes sections.
- Keyboard shortcuts:
	- `Ctrl+F`: focus file search
	- `Ctrl+N`: add project
	- `Ctrl+C`: copy selected file/folder
	- `Ctrl+X`: cut selected file/folder
	- `Ctrl+V`: paste queued items
	- `Ctrl+Z`: undo last supported file operation
	- `Backspace`: go to parent folder
	- `Delete`: remove selected file/folder or selected note
	- `F5`: global refresh
- Shows project change history and supports viewing history as a text file.
- Supports per-project notes.
- Includes reset functionality with confirmation text for full local data cleanup, including snapshots and recycle bin contents.

## Project Structure

- `main.py`: application entry point.
- `ui.py`: Tkinter UI and user actions.
- `models.py`: dataclasses for `Project`, `TrackedFile`, and `ChangeRecord`.
- `csv_manager.py`: CSV creation/read/write helpers.
- `file_scanner.py`: recursive file scanning and checksum generation.
- `change_detector.py`: change comparison logic.
- `Project Repository File Manager.bat`: Windows launcher with Python detection and venv bootstrapping.
- `app_settings.json`: stores app settings such as custom repository path.
- `repository/`: project folders tracked by the app.
- `projects.csv`, `files.csv`, `change_log.csv`, `todos.csv`: local data files.
- `snapshots/`: automatic file snapshots for compare/restore features.
- `recycle_bin/`: removed files/folders before permanent cleanup.

## Contributions

Developers:

- Bejon Minada

Testers:

- Bejon Minada
- Anselmo Lacuesta II

## Requirements

- Windows
- No Python installation required when using the packaged `.exe`
- Python 3.10 or newer only if running from source (`.py`/`.bat` path)

## How to Run

### Recommended (for end users)

1. Open the `dist` folder.
2. Double-click `Project Repository File Manager.exe`.

This executable is self-contained and does not require installing Python or dependencies.

### Alternative (developer/source mode)

1. Open the app folder.
2. Double-click `Project Repository File Manager.bat`.

The `.bat` launcher will:

1. Ensure the `repository`, `snapshots`, and `recycle_bin` folders exist.
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

## SharePoint and OneDrive Setup Guide

Use this process when your team stores project data in SharePoint and you want this app to work with locally synced paths.

1. Create a SharePoint document library or choose an existing one.
2. In that library, create two folders:
	- `Repository` (project folders tracked by the app)
	- `Backup` (for auto-backups and session archives)
3. In SharePoint, open each folder and click `Add shortcut to OneDrive`.
4. Wait for OneDrive sync to complete on your PC.
5. In File Explorer, verify both synced folders appear under your OneDrive organization path.
6. In the app, open `Settings` and set:
	- `Repository Folder` = local synced path of your SharePoint `Repository`
	- `Backup Folder` = local synced path of your SharePoint `Backup`
7. Save settings and run `Refresh` once.

Notes:
- The app must use the local synced path from OneDrive, not a browser URL.
- Keep repository and backup paths separate; do not set backup inside the repository path.

## Backup Protection Best Practices

To reduce accidental or unauthorized backup changes, apply these controls in SharePoint/OneDrive:

1. Separate ownership:
	- Assign one or two backup managers as folder Owners.
	- Give normal users read-only access to the backup folder when possible.
2. Limit edit/delete permissions:
	- Remove `Edit` for users who only need restore visibility.
	- Avoid granting broad `Full Control` at the parent site when not needed.
3. Use versioning and recycle-bin retention:
	- Enable document library version history.
	- Confirm retention/recycle-bin policies are active.
4. Restrict external sharing for backup content:
	- Disable anonymous links and limit guest access for backup locations.
5. Monitor access and alerts:
	- Enable audit logs and configure alerts for delete or permission changes.
6. Keep backup folder dedicated:
	- Do not use the backup folder for everyday document collaboration.
	- Store only auto-backup snapshots and session capture archives.
7. Test restore regularly:
	- Run a scheduled restore drill (for example monthly) to verify recovery readiness.

## Main Actions

- `Add Project`: creates a new project folder and project record.
- `Settings`: configure the repository folder location.
- `Refresh`: globally refreshes all repository projects and tracked files.
- `Toggle Pin`: pin or unpin a project.
- `Edit Details`: updates project name/description/tags and logs relevant changes.
- `View as Text File`: writes project history to a text file and opens it.
- `Compare to Previous Revision`: saves the current revision when needed, then compares it against the previous saved revision or shows metadata comparison when text diff is not supported.
- `Restore Previous Revision`: rolls the selected file back to the previous saved revision.
- `Remove File/Folder`: removes selected file/folder from disk and tracking.
- `Reset`: deletes all projects, tracked files, notes, CSV records, snapshot revisions, and recycle bin contents after confirmation.

## Data Files

The app stores data in these CSV files in the application folder:

- `projects.csv`
- `files.csv`
- `change_log.csv`
- `todos.csv`

When running the packaged executable, data files are created beside the `.exe` on first launch.

If legacy CSV files exist from an older location, they are migrated automatically on startup.

## Running Tests

Use Python unittest:

```bash
python -m unittest app_test.py
```
