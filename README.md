# Project Repository File Manager 3.2

**Project Repository File Manager** is a local desktop application for organizing project folders, tracking file changes, comparing revisions, restoring snapshots, and managing project notes in a responsive Tkinter workspace.

All data is stored locally in CSV files. No cloud service, external database, or internet connection is required. ✓ Cross-platform support (Windows, macOS, Linux).

## About

Local desktop file and project tracker with change detection, revision management, and session archiving. Designed for teams and individuals managing project repositories locally with full version history and recovery capabilities.

## Core Features

### Project & File Management
- Auto-detects project folders inside the configurable `repository` directory on launch and during global refresh.
- Adds individual files and folders to projects for tracking.
- Built-in file browser with folder navigation (double-click to enter, **Backspace** to go back one level).
- Breadcrumb path display showing current folder depth.
- File-type icons with special icon for compressed archives.
- Per-file and folder operations: open, rename (**F2**), remove.

### Change Detection & Versioning
- Checksum-based change detection (SHA-256) with change types: `ADD`, `REMOVE`, `MODIFY`, `MOVE`, `META_UPDATE`.
- Snapshot support for tracked files with restore capability.
- Diff view for text files using previous snapshots; metadata fallback for binary files.
- Restore any previous file revision with timestamp reference.

### Repository & Settings
- Configurable repository path via Settings (supports OneDrive-synced SharePoint folders, network drives, etc.).
- Global **Refresh** scans entire repository and updates all project/file metadata.
- Checksum cache reuse for unchanged files (faster scans on large repositories).
- Auto-generated backup folders: `Backups/` (timestamped) and `Session/` (for session archives).
- Restore one or multiple projects from timestamped backup folder (multi-select + Restore All).

### File Operations & Clipboard
- Queued **Copy** and **Move** actions with multi-file support.
- Paste operations with collision detection and auto-numbered duplicates (`name(1)`, `name(2)`, etc.).
- Context menu tools:
	- Extract Selected Archives Here
	- Compress Selected Items to ZIP
	- Compress Folder to ZIP (preserves folder names with dots, e.g., "test program rev. 1.zip")

### Organization & Filtering
- Project pinning/favorites and custom tag editing.
- Advanced file filtering by filename, extension, note text.
- History filter by change type with searchable export.
- Activity dashboard with project statistics and most-active ranking.

### Data Safety & Recovery
- Recycle bin for file removals (soft delete with restore option).
- Project-scoped recycle bin restore with multi-select and Restore All support.
- Auto-backup before data-destructive operations (Reset, Restore).
- Session capture/restore via ZIP with default paths in `Backups/Session/`.

### UI & Keyboard Shortcuts
- Responsive right-side panel: Details, History, Project Notes (scrollable).
- Keyboard shortcuts:
	- `Ctrl+F` → Focus file search
	- `Ctrl+N` → Add project
	- `Ctrl+C` → Copy selected file/folder
	- `Ctrl+X` → Cut selected file/folder
	- `Ctrl+V` → Paste queued items
	- `Ctrl+Z` → Undo last supported operation
	- **`Backspace`** → Go back one folder level
	- `Delete` → Remove selected file/folder or note
	- `F2` → Rename selected file or folder
	- `F5` → Global refresh

## Technical Stack

- **Language**: Python 3.14
- **UI Framework**: Tkinter + TTK (built-in, no external GUI dependencies)
- **Packaging**: PyInstaller (single-file executable)
- **Data Storage**: CSV files (human-readable, version-control friendly)
- **Hashing**: SHA-256 for change detection
- **Platform**: Windows, macOS, Linux

## Installation & Usage

1. Download the latest executable: `Project Repository File Manager.exe` (Windows) or run `python main.py` (cross-platform).
2. On first launch, configure the repository path (defaults to `./repository`).
3. Add projects and files to track; files are scanned for changes on refresh.
4. Use snapshot/diff workflows to compare and restore file versions.
5. Archive sessions or export history as needed.

## Data Storage

- **Projects** → `projects.csv`
- **Tracked Files** → `files.csv`
- **Change Log** → `change_log.csv`
- **Project Notes** → `todos.csv`, `item_inventory.csv`
- **Settings** → `app_settings.json`
- **Backups** → `Backups/` (timestamped folders)
- **Archives** → `Session/` (session ZIP files)
- **Recycle Bin** → `recycle_bin/` (removed files)
- **Snapshots** → `snapshots/` (file versions for diff/restore)

## Keyboard Navigation

| Key | Action |
|-----|--------|
| `F5` | Refresh all projects and files |
| `Backspace` | Navigate back one folder level in file browser |
| `Ctrl+F` | Focus file search input |
| `Ctrl+N` | Add new project |
| `Ctrl+C` | Copy file/folder to clipboard queue |
| `Ctrl+X` | Cut file/folder to clipboard queue |
| `Ctrl+V` | Paste queued items (with collision handling) |
| `Ctrl+Z` | Undo last file operation |
| `Delete` | Soft-delete selected item to recycle bin |
| `F2` | Rename selected file or folder |

## Performance Notes

- Refresh uses cached checksums; only new/modified files are re-hashed.
- Large repositories (1000+ files) scan in seconds on modern hardware.
- Archive operations use ZIP compression with streaming for memory efficiency.
- Recycle bin integrates with system cleanup tools.

## Troubleshooting

**"Could not create backup before reset"**
- Ensure backup folder path is writable and not on a network with connectivity issues.

**Files not updating in refresh**
- Verify tracked files exist and are readable; check permissions.
- Large files (>1GB) may take longer to hash.

**Archive extraction fails**
- Ensure target folder has write permissions.
- Check disk space for extraction.

## Version History

- **3.2** – Multi-select + Restore All in recycle bin and auto-backup restore dialogs; F2 rename for files and folders; Ctrl+A in recycle bin dialog; full horizontal and vertical scrollbars on all text boxes; restore history logging.
- **3.1** – Fixed folder ZIP naming (preserves dots in folder names), enhanced reset to force-delete locked folders, cleanup.
- **3.0** – Performance optimization, terminal integration, long-path support on Windows.
- **2.x** – Initial stable release.

## License

See LICENSE file.

## Contributing

To contribute, fork the repository, make changes, test thoroughly, and submit a pull request to the main branch.
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
- `repository/Project Repository File Manager/`: app data folder (`projects.csv`, `files.csv`, `change_log.csv`, `todos.csv`, `item_inventory.csv`).
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

The app stores data in these CSV files inside `repository/Project Repository File Manager/`:

- `projects.csv`
- `files.csv`
- `change_log.csv`
- `todos.csv`
- `item_inventory.csv`

When running the packaged executable, the data folder is created under the configured repository path on first launch.

If legacy CSV files exist from an older location, they are migrated automatically on startup.

## Running Tests

Use Python unittest:

```bash
python -m unittest app_test.py
```
