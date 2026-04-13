import os
import json
import shutil
import subprocess
import sys
import time
import tempfile
import tkinter as tk
import difflib
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional

from change_detector import detect_changes
from csv_manager import CSVManager
from file_scanner import compute_checksum, scan_project_files
from models import ChangeRecord, Project, TrackedFile

APP_VERSION = "3.0"
APP_SETTINGS_FILE = "app_settings.json"
SHARED_REPO_SETTINGS_DIR = "Project Repository File Manager"
SHARED_REPO_SETTINGS_FILE = "shared_settings.json"
BACKUPS_SUBDIR = "Backups"
SESSIONS_SUBDIR = "Session"

class DocumentTrackerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Project Repository File Manager")
        self.folder_icon = tk.PhotoImage(width=16, height=16)
        self.folder_icon.put("#f7c600", to=(0, 5, 15, 15))
        self.folder_icon.put("#e0a800", to=(0, 3, 10, 7))
        self.folder_icon.put("#d18b00", to=(0, 0, 15, 4))
        self.root.iconphoto(False, self.folder_icon)
        self.tree_folder_icon = self._create_folder_icon("#f0c240", "#d9a72f")
        self.tree_file_icons = {
            "python": self._create_file_icon("#4b8bbe", "python"),
            "text": self._create_file_icon("#8e8e8e", "text"),
            "markdown": self._create_file_icon("#3d6db5", "markdown"),
            "csv": self._create_file_icon("#2f9e44", "csv"),
            "json": self._create_file_icon("#f08c00", "json"),
            "xml": self._create_file_icon("#c77dff", "xml"),
            "pdf": self._create_file_icon("#d62828", "pdf"),
            "image": self._create_file_icon("#e76f51", "image"),
            "archive": self._create_zip_folder_icon(),
            "doc": self._create_file_icon("#1565c0", "doc"),
            "sheet": self._create_file_icon("#2e7d32", "sheet"),
            "slide": self._create_file_icon("#ef6c00", "slide"),
            "audio": self._create_file_icon("#6a4c93", "audio"),
            "video": self._create_file_icon("#9c27b0", "video"),
            "generic": self._create_file_icon("#9e9e9e", "generic"),
        }
        if getattr(sys, 'frozen', False):
            self.app_base_dir = Path(sys.executable).resolve().parent
        else:
            self.app_base_dir = Path(__file__).resolve().parent
        self.settings_path = self.app_base_dir / APP_SETTINGS_FILE
        self.repository_folder = self._load_repository_folder()
        self.repository_folder.mkdir(parents=True, exist_ok=True)
        self.data_folder = self.repository_folder / SHARED_REPO_SETTINGS_DIR
        self.data_folder.mkdir(parents=True, exist_ok=True)
        self.csv = CSVManager(base_dir=self.data_folder)
        self.backup_folder = self._load_backup_folder(self.repository_folder)
        if self.backup_folder is not None:
            self.backup_folder.mkdir(parents=True, exist_ok=True)
            self._ensure_backup_subfolders(self.backup_folder)
        self.snapshots_folder = self.app_base_dir / "snapshots"
        self.snapshots_folder.mkdir(parents=True, exist_ok=True)
        self.recycle_bin_folder = self.app_base_dir / "recycle_bin"
        self.recycle_bin_folder.mkdir(parents=True, exist_ok=True)
        self.recycle_manifest_path = self.recycle_bin_folder / "manifest.json"
        self.projects: List[Project] = []
        self.tracked_files: List[TrackedFile] = []
        self.selected_project: Optional[Project] = None
        self.selected_file: Optional[TrackedFile] = None
        self.current_folder_rel: str = ""
        self.selected_item_kind: str = ""
        self.selected_item_rel: str = ""
        self.pending_file_operation: Optional[dict[str, object]] = None
        self.undo_stack: List[dict[str, object]] = []
        self.sort_state = {
            "projects": {"name": False, "tags": False},
            "files": {"path": False, "size": False, "modified": False},
        }
        self._busy_started_at: Optional[float] = None
        self._busy_hide_after_id: Optional[str] = None
        self._busy_mode = "indeterminate"
        self.project_todos: dict[str, List[dict]] = {}
        self.project_tree_name_ratio = 0.68
        self.file_tree_name_ratio = 0.62
        self.file_tree_size_ratio = 0.14
        self.scale_factor = 1.0
        self.base_window_width = 1200
        self._build_ui()
        self._bind_shortcuts()
        self.root.bind("<Configure>", self._on_window_resize)
        self._ensure_backup_folder_configured()
        if not self.root.winfo_exists():
            return
        self._auto_sync_repository()
        self.refresh_projects()

    def _build_ui(self) -> None:
        self.root.geometry("1200x700")
        self.root.minsize(720, 400)  # Minimum window size for usability
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top_frame = ttk.Frame(self.root, padding=(8, 4))
        top_frame.grid(row=0, column=0, sticky="ew")
        top_frame.columnconfigure(1, weight=1)
        self.about_window_icon = self._create_info_icon()
        self.settings_window_icon = self._create_gear_icon()
        ttk.Button(top_frame, text="About", command=self.show_about).grid(row=0, column=0, sticky="w")
        ttk.Button(top_frame, text="Settings", command=self.open_settings).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.data_actions_button = ttk.Menubutton(top_frame, text="Data Actions")
        self.data_actions_button.grid(row=0, column=2, sticky="e")
        self.data_actions_menu = tk.Menu(self.data_actions_button, tearoff=0)
        self.data_actions_menu.add_command(label="Capture Session (ZIP)", command=self.export_backup)
        self.data_actions_menu.add_command(label="Restore Session (ZIP)", command=self.import_backup)
        self.data_actions_menu.add_command(label="Restore Project from Auto-Backup", command=self.restore_project_from_backup)
        self.data_actions_menu.add_command(label="Restore Recycle Bin Item", command=self.restore_recycle_item)
        self.data_actions_menu.add_separator()
        self.data_actions_menu.add_command(label="Reset", command=self.reset_all_data)
        self.data_actions_button["menu"] = self.data_actions_menu

        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.grid(row=1, column=0, sticky="nsew")

        left_frame = ttk.Frame(self.main_pane, padding=(8, 8))
        center_frame = ttk.Frame(self.main_pane, padding=(8, 8))
        right_frame = ttk.Frame(self.main_pane, padding=(8, 8))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)
        self.main_pane.add(left_frame, weight=1)
        self.main_pane.add(center_frame, weight=4)
        self.main_pane.add(right_frame, weight=1)
        self.main_pane.bind("<Double-1>", self._on_main_pane_double_click)

        def _set_initial_sash_positions() -> None:
            total = self.main_pane.winfo_width()
            side = total // 6          # ~1/6 of total for each side panel
            self.main_pane.sashpos(0, side)
            self.main_pane.sashpos(1, total - side)

        self.root.after(0, _set_initial_sash_positions)

        project_label = ttk.Label(left_frame, text="Projects")
        project_label.pack(anchor="w")
        search_frame = ttk.Frame(left_frame)
        search_frame.pack(fill="x", pady=(4, 8))
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.project_search_entry = ttk.Entry(search_frame)
        self.project_search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.project_search_entry.bind("<KeyRelease>", lambda event: self.refresh_projects())

        self.project_tree = ttk.Treeview(left_frame, columns=("name", "tags"), show="headings", height=20, selectmode="browse")
        self.project_tree.heading("name", text="Project Name", command=lambda: self._sort_project_tree("name"))
        self.project_tree.heading("tags", text="Tags", command=lambda: self._sort_project_tree("tags"))
        self.project_tree.column("name", width=120, anchor="w", stretch=False)
        self.project_tree.column("tags", width=60, anchor="w", stretch=False)
        self.project_tree.bind("<<TreeviewSelect>>", self.on_project_select)
        self.project_tree.bind("<Button-1>", self._project_tree_click, add="+")
        self.project_tree.bind("<Double-1>", self.on_project_tree_double_click)
        self.project_tree.bind("<Button-3>", self.show_project_context_menu)
        self.project_tree.bind("<Configure>", lambda event: self._fit_project_tree_columns())
        self.project_tree.pack(fill="both", expand=True)
        self.root.after(0, self._fit_project_tree_columns)

        self.project_context_menu = tk.Menu(self.root, tearoff=0)
        self.project_context_menu.add_command(label="Go To Folder", command=self.go_to_folder_directory)
        self.project_context_menu.add_command(label="View Project Details", command=self.view_project_details)
        self.project_context_menu.add_command(label="Edit Details", command=self.edit_project_details)
        self.project_context_menu.add_command(label="Toggle Pin", command=self.toggle_project_pin)
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(label="Delete Project Folder", command=self.delete_project_folder)

        self.project_empty_context_menu = tk.Menu(self.root, tearoff=0)
        self.project_empty_context_menu.add_command(label="Add Project", command=self.add_project)

        project_buttons = ttk.Frame(left_frame)
        project_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(project_buttons, text="Add Project", command=self.add_project).pack(side="left")
        self.refresh_button = ttk.Button(project_buttons, text="Refresh", command=self.refresh_repository)
        self.refresh_button.pack(side="left", padx=(4, 0))

        file_label = ttk.Label(center_frame, text="Tracked Files")
        file_label.pack(anchor="w")
        filter_frame = ttk.Frame(center_frame)
        filter_frame.pack(fill="x", pady=(4, 8))
        ttk.Label(filter_frame, text="Search filename:").grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(filter_frame)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.search_entry.bind("<KeyRelease>", lambda event: self.refresh_files())
        ttk.Label(filter_frame, text="Extension:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.extension_combo = ttk.Combobox(filter_frame, width=12, state="readonly")
        self.extension_combo.grid(row=0, column=3, sticky="w", padx=4)
        self.extension_combo['values'] = [""]
        self.extension_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh_files())
        ttk.Label(filter_frame, text="File notes contain:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.note_filter_entry = ttk.Entry(filter_frame)
        self.note_filter_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
        self.note_filter_entry.bind("<KeyRelease>", lambda event: self.refresh_files())
        filter_frame.columnconfigure(1, weight=1)

        self.breadcrumb_label = ttk.Label(center_frame, text="Path: /")
        self.breadcrumb_label.pack(anchor="w", pady=(0, 4))
        self.file_tree = ttk.Treeview(center_frame, columns=("size", "modified"), show="tree headings", height=20, selectmode="extended")
        self.file_tree.heading("#0", text="Item Name", command=lambda: self._sort_file_tree("path"))
        self.file_tree.heading("size", text="Size", command=lambda: self._sort_file_tree("size"))
        self.file_tree.heading("modified", text="Last Modified", command=lambda: self._sort_file_tree("modified"))
        self.file_tree.column("#0", width=420, anchor="w")
        self.file_tree.column("size", width=100, anchor="w")
        self.file_tree.column("modified", width=170, anchor="w")
        self.file_tree_base_name_width = 420
        self.file_tree_base_size_width = 100
        self.file_tree_base_modified_width = 170
        self.file_tree.bind("<<TreeviewSelect>>", self.on_file_select)
        self.file_tree.bind("<Button-1>", self._file_tree_click, add="+")
        self.file_tree.bind("<Control-Button-1>", self._file_tree_ctrl_click, add="+")
        self.file_tree.bind("<Shift-Button-1>", self._file_tree_shift_click, add="+")
        self.file_tree.bind("<Double-1>", self.on_file_double_click)
        self.file_tree.bind("<Button-3>", self.show_file_context_menu)
        self.file_tree.bind("<Configure>", lambda event: self._fit_file_tree_columns())
        self.file_tree.pack(fill="both", expand=True)
        self.root.after(0, self._fit_file_tree_columns)

        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="Add/Edit File Notes", command=self.add_file_note)
        self.file_context_menu.add_command(label="Open File", command=self.open_file)
        self.file_context_menu.add_command(label="Rename File", command=self.rename_file)
        self.file_context_menu.add_command(label="Copy File", command=self.copy_selected_items)
        self.file_context_menu.add_command(label="Move File", command=self.move_selected_items)
        self.file_context_menu.add_command(label="Extract Selected Archives Here", command=self.extract_selected_archives_here)
        self.file_context_menu.add_command(label="Compress Selected to ZIP...", command=self.compress_selected_items_to_zip)
        self.file_context_menu.add_command(label="Compress Folder to ZIP", command=self.compress_selected_folders_to_zip)
        self.file_context_menu.add_command(label="Compare to Previous Revision", command=self.compare_to_previous_revision)
        self.file_context_menu.add_command(label="Restore Previous Revision", command=self.restore_previous_revision)
        self.file_context_menu.add_separator()
        self.file_context_menu.add_command(label="Remove Selected", command=self.remove_item)

        self.file_destination_menu = tk.Menu(self.root, tearoff=0)

        file_buttons = ttk.Frame(center_frame)
        file_buttons.pack(fill="x", pady=(8, 0))
        self.add_files_button = ttk.Button(file_buttons, text="Add Files", command=self.add_files)
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(file_buttons, text="Add Folder", command=self.add_folder)
        self.add_folder_button.pack(side="left", padx=(4, 0))
        self.back_button = ttk.Button(file_buttons, text="Back", command=self.go_back_folder)
        self.back_button.pack(side="left", padx=(4, 0))

        # Keep the progress controls in the existing bottom action row so the
        # layout stays stable during long-running operations.
        self.busy_container = ttk.Frame(file_buttons)
        self.busy_container.pack(side="right", padx=(4, 0))
        self.busy_message_var = tk.StringVar(value="")
        self.busy_detail_var = tk.StringVar(value="")

        self.busy_label = ttk.Label(self.busy_container, textvariable=self.busy_message_var)
        self.busy_label.pack(side="left", padx=(0, 6))

        self.busy_progress = ttk.Progressbar(
            self.busy_container,
            orient=tk.HORIZONTAL,
            mode="indeterminate",
            length=180,
            maximum=100,
        )
        self.busy_progress.pack(side="left", padx=(0, 6))

        self.busy_detail_label = ttk.Label(self.busy_container, textvariable=self.busy_detail_var, width=12)
        self.busy_detail_label.pack(side="left")

        self.dashboard_frame = ttk.Frame(right_frame)
        self.dashboard_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.dashboard_frame.bind("<Configure>", lambda event: self._update_dashboard())

        # Create scrollable canvas for content sections
        self.right_scroll_canvas = tk.Canvas(right_frame, highlightthickness=0)
        self.right_scroll_canvas.grid(row=1, column=0, sticky="nsew")

        self.right_scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=self.right_scroll_canvas.yview)
        self.right_scrollbar.grid(row=1, column=1, sticky="ns")

        self.right_scroll_canvas.configure(yscrollcommand=self.right_scrollbar.set)
        self.content_frame = ttk.Frame(self.right_scroll_canvas)
        self.content_window = self.right_scroll_canvas.create_window((0, 0), window=self.content_frame, anchor="nw")

        def on_content_configure(event: object) -> None:
            self.right_scroll_canvas.configure(scrollregion=self.right_scroll_canvas.bbox("all"))

        def on_canvas_configure(event: tk.Event) -> None:
            self.right_scroll_canvas.itemconfig(self.content_window, width=event.width)

        self.content_frame.bind("<Configure>", on_content_configure)
        self.right_scroll_canvas.bind("<Configure>", on_canvas_configure)

        tiles_row = ttk.Frame(self.dashboard_frame)
        tiles_row.pack(fill="x")
        tiles_row.columnconfigure(0, weight=1)
        tiles_row.columnconfigure(1, weight=1)

        proj_tile = ttk.Frame(tiles_row, relief="groove", padding=(6, 4))
        proj_tile.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Label(proj_tile, text="PROJECTS", font=("TkDefaultFont", 7)).pack(anchor="w")
        self.dashboard_total_projects = ttk.Label(proj_tile, text="0", font=("TkDefaultFont", 14, "bold"))
        self.dashboard_total_projects.pack(anchor="w")
        self.dash_projects_bar = tk.Canvas(proj_tile, height=3, highlightthickness=0, bg="#e0e0e0")
        self.dash_projects_bar.pack(fill="x", pady=(2, 0))

        files_tile = ttk.Frame(tiles_row, relief="groove", padding=(6, 4))
        files_tile.grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ttk.Label(files_tile, text="FILES", font=("TkDefaultFont", 7)).pack(anchor="w")
        self.dashboard_total_files = ttk.Label(files_tile, text="0", font=("TkDefaultFont", 14, "bold"))
        self.dashboard_total_files.pack(anchor="w")
        self.dash_files_bar = tk.Canvas(files_tile, height=3, highlightthickness=0, bg="#e0e0e0")
        self.dash_files_bar.pack(fill="x", pady=(2, 0))

        activity_tile = ttk.Frame(self.dashboard_frame, relief="groove", padding=(6, 4))
        activity_tile.pack(fill="x", pady=(4, 0))
        act_top = ttk.Frame(activity_tile)
        act_top.pack(fill="x")
        ttk.Label(act_top, text="7-DAY ACTIVITY", font=("TkDefaultFont", 7)).pack(side="left")
        self.dashboard_changes_today = ttk.Label(act_top, text="0 today", font=("TkDefaultFont", 7))
        self.dashboard_changes_today.pack(side="right")
        self.dash_activity_canvas = tk.Canvas(activity_tile, height=38, highlightthickness=0, bg="#f5f5f5")
        self.dash_activity_canvas.pack(fill="x", pady=(3, 0))

        active_tile = ttk.Frame(self.dashboard_frame, relief="groove", padding=(6, 4))
        active_tile.pack(fill="x", pady=(4, 0))
        ttk.Label(active_tile, text="TOP PROJECTS", font=("TkDefaultFont", 7)).pack(anchor="w")
        self.dashboard_active_project = ttk.Label(active_tile, text="N/A", font=("TkDefaultFont", 8, "bold"), wraplength=140)
        self.dashboard_active_project.pack(anchor="w")
        self.dash_top_canvas = tk.Canvas(active_tile, height=44, highlightthickness=0, bg="#f5f5f5")
        self.dash_top_canvas.pack(fill="x", pady=(3, 0))

        detail_label = ttk.Label(self.content_frame, text="File Details")
        detail_label.pack(anchor="w")
        self.details_text = tk.Text(self.content_frame, height=10, wrap="word", state="disabled")
        self.details_text_base_height = 10
        self.details_text.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))
        history_label = ttk.Label(self.content_frame, text="Project Change History")
        history_label.pack(anchor="w", pady=(2, 0))
        self.history_filter_combo = ttk.Combobox(self.content_frame, state="readonly", width=20)
        self.history_filter_combo["values"] = ["ALL", "ADD", "REMOVE", "MODIFY", "MOVE", "META_UPDATE", "NOTE", "EDIT", "RENAME", "RESTORE", "MANUAL_REMOVE", "NOTE_ADD", "NOTE_EDIT", "NOTE_REMOVE"]
        self.history_filter_combo.set("ALL")
        self.history_filter_combo.bind("<<ComboboxSelected>>", lambda event: self._show_history())
        self.history_filter_combo.pack(anchor="w", pady=(2, 2))
        self.history_text = tk.Text(self.content_frame, height=10, wrap="word", state="disabled")
        self.history_text_base_height = 10
        self.history_text.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))
        history_button_frame = ttk.Frame(self.content_frame)
        history_button_frame.pack(fill="x", pady=(0, 4))
        self.view_history_button = ttk.Button(history_button_frame, text="View as Text File", command=self.print_project_history)
        self.view_history_button.pack(side="right")

        todo_label = ttk.Label(self.content_frame, text="Project Notes")
        todo_label.pack(anchor="w", pady=(2, 0))
        self.todo_listbox = tk.Listbox(self.content_frame, selectmode="extended")
        self.todo_listbox_base_height = 10
        self.todo_listbox.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))
        self.todo_listbox.bind("<Button-1>", self._todo_listbox_click)
        self.todo_listbox.bind("<Control-Button-1>", self._todo_listbox_ctrl_click)
        self.todo_listbox.bind("<Shift-Button-1>", self._todo_listbox_shift_click)
        self.todo_listbox.bind("<Button-3>", self.show_todo_context_menu)
        self.todo_listbox.bind("<Double-1>", lambda event: self.open_todo_item())
        self.todo_context_menu = tk.Menu(self.root, tearoff=0)
        self.todo_context_menu.add_command(label="Open/Edit Note", command=self.open_todo_item)
        self.todo_context_menu.add_separator()
        self.todo_context_menu.add_command(label="Add Note", command=self.add_todo_item)
        self.todo_context_menu.add_command(label="Remove Note", command=self.remove_todo_item)
        self.todo_empty_context_menu = tk.Menu(self.root, tearoff=0)
        self.todo_empty_context_menu.add_command(label="Add Note", command=self.add_todo_item)
        todo_buttons_frame = ttk.Frame(self.content_frame)
        todo_buttons_frame.pack(fill="x", pady=(0, 0))
        self.add_note_button = ttk.Button(todo_buttons_frame, text="Add Note", command=self.add_todo_item)
        self.add_note_button.pack(side="left")
        self.remove_note_button = ttk.Button(todo_buttons_frame, text="Remove Selected", command=self.remove_todo_item)
        self.remove_note_button.pack(side="left", padx=(4, 0))
        self._bind_right_panel_mousewheel(right_frame)
        self._update_file_action_buttons_state()
        # Ensure progress bar starts in idle state (no animation or fill)
        self._hide_busy_widgets()

    def _bind_right_panel_mousewheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_right_panel_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_right_panel_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_right_panel_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_right_panel_mousewheel(child)

    def _set_busy(self, is_busy: bool, message: str = "Processing...") -> None:
        if is_busy:
            if self._busy_hide_after_id is not None:
                self.root.after_cancel(self._busy_hide_after_id)
                self._busy_hide_after_id = None
            if self._busy_started_at is None:
                self._busy_started_at = time.monotonic()

            self.busy_message_var.set(message)
            self.busy_detail_var.set("")
            self._busy_mode = "indeterminate"
            self.busy_progress.configure(length=180)
            self.busy_progress.stop()
            self.busy_progress.configure(mode="indeterminate", maximum=100)
            self.busy_progress["value"] = 0
            self.busy_progress.start(12)

            self.root.configure(cursor="watch")
            self.root.update_idletasks()
        else:
            min_visible_seconds = 0.50
            if self._busy_started_at is None:
                self._hide_busy_widgets()
            else:
                elapsed = time.monotonic() - self._busy_started_at
                remaining_ms = int(max(0.0, (min_visible_seconds - elapsed) * 1000))
                if remaining_ms > 0:
                    self._busy_hide_after_id = self.root.after(remaining_ms, self._hide_busy_widgets)
                else:
                    self._hide_busy_widgets()

    def _set_busy_progress(self, value: float, maximum: Optional[float] = None, message: Optional[str] = None) -> None:
        if maximum is not None:
            self.busy_progress.configure(maximum=max(1, maximum))
        if self._busy_mode != "determinate":
            self.busy_progress.stop()
            self.busy_progress.configure(mode="determinate")
            self._busy_mode = "determinate"

        max_value = float(self.busy_progress.cget("maximum"))
        clamped_value = max(0.0, min(value, max_value))
        self.busy_progress["value"] = clamped_value
        if message is not None:
            self.busy_message_var.set(message)
        if max_value > 0:
            self.busy_detail_var.set(f"{int(clamped_value)} / {int(max_value)}")
        else:
            self.busy_detail_var.set("")
        self.root.update_idletasks()

    def _hide_busy_widgets(self) -> None:
        self._busy_hide_after_id = None
        self._busy_started_at = None
        self._busy_mode = "indeterminate"
        self.busy_progress.stop()
        self.busy_progress.configure(length=0, mode="indeterminate", maximum=100)
        self.busy_progress["value"] = 0
        self.busy_message_var.set("")
        self.busy_detail_var.set("")
        self.root.configure(cursor="")

    def _on_right_panel_mousewheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            raw_delta = int(getattr(event, "delta", 0))
            if raw_delta == 0:
                return "break"
            delta = -int(raw_delta / 120) if sys.platform.startswith("win") else (-1 if raw_delta > 0 else 1)
            if delta == 0:
                delta = -1 if raw_delta > 0 else 1

        self.right_scroll_canvas.yview_scroll(delta, "units")
        return "break"

    def refresh_projects(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        search_terms = [term for term in self.project_search_entry.get().strip().lower().split() if term]
        project_rows = [row for row in self.csv.read_rows("projects") if not self._is_internal_project_row(row)]
        self.projects = [Project.from_dict(row) for row in project_rows]
        self.projects.sort(key=lambda p: (p.pinned != "1", p.project_name.lower()))
        for project in self.projects:
            project_text = f"{project.project_name} {project.tags} {project.root_path}".lower()
            if search_terms and not all(term in project_text for term in search_terms):
                continue
            display_name = f"* {project.project_name}" if project.pinned == "1" else project.project_name
            self.project_tree.insert("", "end", iid=project.project_id, values=(display_name, project.tags))
        self._update_dashboard()

    def _is_internal_project_row(self, row: dict[str, str]) -> bool:
        return row.get("project_name", "") == SHARED_REPO_SETTINGS_DIR or Path(row.get("root_path", "")).name == SHARED_REPO_SETTINGS_DIR

    def go_to_folder_directory(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        project_root = Path(self.selected_project.root_path)
        if not project_root.exists():
            messagebox.showerror("Missing folder", "Project root folder does not exist.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(project_root)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(project_root)])
            else:
                subprocess.run(["xdg-open", str(project_root)])
        except Exception as exc:
            messagebox.showerror("Open failed", f"Could not open folder: {exc}")

    def _load_repository_folder(self) -> Path:
        default_path = self.app_base_dir / "repository"
        if not self.settings_path.exists():
            return default_path

        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return default_path

        raw_path = str(data.get("repository_path", "")).strip()
        if not raw_path:
            return default_path

        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (self.app_base_dir / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _shared_repo_settings_path(self, repository_folder: Path) -> Path:
        return repository_folder / SHARED_REPO_SETTINGS_DIR / SHARED_REPO_SETTINGS_FILE

    def _ensure_backup_subfolders(self, backup_folder: Path) -> None:
        backup_workspace = backup_folder.resolve() / SHARED_REPO_SETTINGS_DIR
        (backup_workspace / BACKUPS_SUBDIR).mkdir(parents=True, exist_ok=True)
        (backup_workspace / SESSIONS_SUBDIR).mkdir(parents=True, exist_ok=True)

    def _session_archive_root(self) -> Optional[Path]:
        if not self.backup_folder:
            return None
        session_root = self.backup_folder.resolve() / SHARED_REPO_SETTINGS_DIR / SESSIONS_SUBDIR
        session_root.mkdir(parents=True, exist_ok=True)
        return session_root

    def _load_shared_backup_folder(self, repository_folder: Path) -> Optional[Path]:
        settings_path = self._shared_repo_settings_path(repository_folder)
        if not settings_path.exists():
            return None

        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        raw_path = str(data.get("backup_path", "")).strip()
        if not raw_path:
            return None

        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (repository_folder / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _load_backup_folder(self, repository_folder: Optional[Path] = None) -> Optional[Path]:
        local_backup: Optional[Path] = None
        if self.settings_path.exists():
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                raw_path = str(data.get("backup_path", "")).strip()
                if raw_path:
                    candidate = Path(raw_path).expanduser()
                    if not candidate.is_absolute():
                        candidate = (self.app_base_dir / candidate).resolve()
                    else:
                        candidate = candidate.resolve()
                    local_backup = candidate
            except Exception:
                pass

        if repository_folder is None:
            return local_backup

        shared_backup = self._load_shared_backup_folder(repository_folder)
        if shared_backup is not None:
            if local_backup is None or local_backup != shared_backup:
                self._save_settings(repository_folder, shared_backup, write_shared=False)
            return shared_backup
        return local_backup

    def _write_shared_backup_folder(self, repository_folder: Path, backup_folder: Path) -> None:
        shared_path = self._shared_repo_settings_path(repository_folder)
        shared_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "backup_path": str(backup_folder),
            "updated_at": datetime.now().isoformat(),
        }
        shared_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _save_settings(self, repository_folder: Path, backup_folder: Path, write_shared: bool = True) -> None:
        payload = {
            "repository_path": str(repository_folder),
            "backup_path": str(backup_folder),
        }
        self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if write_shared:
            self._write_shared_backup_folder(repository_folder, backup_folder)

    def _paths_overlap(self, path_a: Path, path_b: Path) -> bool:
        return path_a == path_b or path_a in path_b.parents or path_b in path_a.parents

    def _find_project_by_id(self, project_id: str) -> Optional[Project]:
        return next((project for project in self.projects if project.project_id == project_id), None)

    def _load_recycle_manifest(self) -> List[dict[str, str]]:
        if not self.recycle_manifest_path.exists():
            return []
        try:
            payload = json.loads(self.recycle_manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return [entry for entry in payload if isinstance(entry, dict)]
        except Exception:
            pass
        return []

    def _save_recycle_manifest(self, rows: List[dict[str, str]]) -> None:
        self.recycle_manifest_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def _ensure_backup_folder_configured(self) -> None:
        if self.backup_folder and not self._paths_overlap(self.repository_folder.resolve(), self.backup_folder.resolve()):
            return

        messagebox.showwarning(
            "Backup folder required",
            "A backup folder is required before using the app. Set it in Settings.",
            parent=self.root,
        )
        self.open_settings(force_backup=True)

        if self.backup_folder and not self._paths_overlap(self.repository_folder.resolve(), self.backup_folder.resolve()):
            return

        messagebox.showerror(
            "Startup blocked",
            "Backup folder was not configured. The app will now close.",
            parent=self.root,
        )
        self.root.destroy()

    def open_settings(self, force_backup: bool = False) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.iconphoto(False, self.settings_window_icon)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("760x250")
        dialog.resizable(False, False)

        ttk.Label(dialog, text="Repository Folder:").pack(anchor="w", padx=12, pady=(12, 4))
        path_var = tk.StringVar(value=str(self.repository_folder))

        path_row = ttk.Frame(dialog)
        path_row.pack(fill="x", padx=12)
        ttk.Entry(path_row, textvariable=path_var).pack(side="left", fill="x", expand=True)

        def browse_folder() -> None:
            selected = filedialog.askdirectory(
                title="Select repository folder",
                initialdir=path_var.get() or str(self.app_base_dir),
            )
            if selected:
                path_var.set(selected)
                shared_backup = self._load_shared_backup_folder(Path(selected).expanduser().resolve())
                if shared_backup is not None:
                    backup_var.set(str(shared_backup))

        ttk.Button(path_row, text="Browse", command=browse_folder).pack(side="left", padx=(8, 0))

        ttk.Label(dialog, text="Backup Folder (required):").pack(anchor="w", padx=12, pady=(10, 4))
        backup_var = tk.StringVar(value=str(self.backup_folder) if self.backup_folder else "")

        backup_row = ttk.Frame(dialog)
        backup_row.pack(fill="x", padx=12)
        ttk.Entry(backup_row, textvariable=backup_var).pack(side="left", fill="x", expand=True)

        def browse_backup_folder() -> None:
            selected = filedialog.askdirectory(
                title="Select backup folder",
                initialdir=backup_var.get() or str(self.app_base_dir),
            )
            if selected:
                backup_var.set(selected)

        ttk.Button(backup_row, text="Browse", command=browse_backup_folder).pack(side="left", padx=(8, 0))

        ttk.Label(
            dialog,
            text="Tip: Backup folder must be outside the repository folder.",
        ).pack(anchor="w", padx=12, pady=(8, 0))

        button_row = ttk.Frame(dialog)
        button_row.pack(fill="x", padx=12, pady=(14, 0))

        def save_settings() -> None:
            target = Path(path_var.get().strip()).expanduser()
            if not path_var.get().strip():
                messagebox.showwarning("Settings", "Please choose a repository folder.", parent=dialog)
                return

            target = target.resolve()

            backup_input = backup_var.get().strip()
            if not backup_input:
                shared_backup = self._load_shared_backup_folder(target)
                if shared_backup is not None:
                    backup_var.set(str(shared_backup))
                    backup_input = str(shared_backup)
                else:
                    messagebox.showwarning("Settings", "Please choose a backup folder.", parent=dialog)
                    return

            backup_target = Path(backup_input).expanduser()

            try:
                target.mkdir(parents=True, exist_ok=True)
                target = target.resolve()
                backup_target.mkdir(parents=True, exist_ok=True)
                backup_target = backup_target.resolve()
                if self._paths_overlap(target, backup_target):
                    messagebox.showerror(
                        "Settings",
                        "Backup folder cannot be the same as repository folder or inside it.",
                        parent=dialog,
                    )
                    return
                self._save_settings(target, backup_target)
                self._ensure_backup_subfolders(backup_target)
            except Exception as exc:
                messagebox.showerror("Settings", f"Could not save settings: {exc}", parent=dialog)
                return

            if target != self.repository_folder:
                self.repository_folder = target
                self.data_folder = self.repository_folder / SHARED_REPO_SETTINGS_DIR
                self.data_folder.mkdir(parents=True, exist_ok=True)
                self.csv = CSVManager(base_dir=self.data_folder)
                self.selected_project = None
                self.selected_file = None
                self.current_folder_rel = ""
                self.pending_file_operation = None
                self.refresh_repository()

            self.backup_folder = backup_target

            dialog.destroy()

        ttk.Button(button_row, text="Save", command=save_settings).pack(side="right")
        if not force_backup:
            ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.wait_window()

    def show_about(self) -> None:
        about_text = (
            f"Project Repository File Manager\n"
            f"Version {APP_VERSION}\n\n"
            "Overview\n"
            "A local first desktop application for organizing project folders, tracking file changes, comparing revisions, "
            "restoring snapshots, and managing notes. The repository can be set to local folders or cloud synced folders such as OneDrive, SharePoint synced libraries, and similar services.\n\n"
            "Latest Functions\n"
            "- Configurable repository location in Settings\n"
                "- Data Actions menu for Capture Session, Restore Session, and Reset\n"
            "- Automatic runtime folder creation on startup\n"
            "- Compare and restore previous file revisions\n"
            "- Queue based copy and move for selected files and folders\n"
            "- Right click empty space to create new files or folders\n"
            "- Dynamic column resizing and double click auto fit behavior\n"
            "- Recycle bin and snapshot support for safer operations\n\n"
            "User Guide\n"
            "1. Create or select a project in the Projects panel.\n"
            "2. Add files or folders to track in Tracked Files.\n"
            "3. Open folders by double clicking folder rows, then press Back or Backspace to go up one level.\n"
            "4. Use right click on a file for rename, notes, compare, restore, copy, move, or remove.\n"
            "5. Use right click on empty space to paste, create a new file, or create a new folder.\n"
                "6. Use Data Actions to capture the current session, restore a saved session, and run a full reset.\n"
            "7. Use Settings to change repository and backup paths (supports OneDrive shortcuts from SharePoint).\n"
            "8. For SharePoint + backup protection best practices, see README.md.\n\n"
            "Keyboard Shortcuts\n"
            "- Ctrl+F: focus file search\n"
            "- Ctrl+N: add project\n"
            "- Ctrl+C: copy selected file or folder\n"
            "- Ctrl+X: cut selected file or folder\n"
            "- Ctrl+V: paste queued items into current folder\n"
            "- Ctrl+Z: undo last supported file operation\n"
            "- Delete: remove selected file or folder\n"
            "- Backspace: go to parent folder\n"
            "- F5: refresh repository\n\n"
            "Developers:\n"
            "Bejon Minada\n\n"
            "Testers:\n"
            "Bejon Minada\n"
            "Anselmo Lacuesta II\n\n"
            f"Main repository folder:\n{self.repository_folder}"
        )

        dialog = tk.Toplevel(self.root)
        dialog.title("About")
        dialog.iconphoto(False, self.about_window_icon)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("760x560")
        dialog.minsize(600, 420)

        text_frame = ttk.Frame(dialog, padding=(10, 10))
        text_frame.pack(fill="both", expand=True)

        about_body = tk.Text(text_frame, wrap="word")
        about_body.pack(side="left", fill="both", expand=True)
        about_body.insert("1.0", about_text)
        about_body.configure(state="disabled")

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=about_body.yview)
        scrollbar.pack(side="right", fill="y")
        about_body.configure(yscrollcommand=scrollbar.set)

        button_row = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        button_row.pack(fill="x")
        ttk.Button(button_row, text="Close", command=dialog.destroy).pack(side="right")

        dialog.wait_window()

    def reset_all_data(self) -> None:
        confirm_dialog = tk.Toplevel(self.root)
        confirm_dialog.title("Reset All Data")
        confirm_dialog.transient(self.root)
        confirm_dialog.grab_set()
        confirm_dialog.geometry("420x180")
        confirm_dialog.resizable(False, False)

        ttk.Label(
            confirm_dialog,
            text="This will permanently delete ALL projects, files,\nhistory, project folders, snapshots, and recycle bin contents.\n\nType  CLEAR ALL DATA  to confirm:",
            justify="center",
        ).pack(pady=(18, 8))
        confirm_entry = ttk.Entry(confirm_dialog, width=30)
        confirm_entry.pack()
        confirm_entry.focus_set()

        button_frame = ttk.Frame(confirm_dialog)
        button_frame.pack(pady=(12, 0))

        def do_reset() -> None:
            if confirm_entry.get().strip() != "CLEAR ALL DATA":
                messagebox.showwarning("Incorrect", "You must type exactly: CLEAR ALL DATA", parent=confirm_dialog)
                return
            try:
                backup_dir = self._create_auto_backup("reset")
            except Exception as exc:
                messagebox.showerror("Auto Backup", f"Could not create backup before reset: {exc}", parent=confirm_dialog)
                return
            confirm_dialog.destroy()
            # Delete all project folders on disk (excluding internal project rows)
            for row in self.csv.read_rows("projects"):
                if self._is_internal_project_row(row):
                    continue
                folder = Path(row.get("root_path", ""))
                if folder.exists() and folder.is_dir():
                    try:
                        shutil.rmtree(folder)
                    except Exception:
                        pass

            # Clear snapshot and recycle-bin contents while preserving folders.
            for managed_folder in (self.snapshots_folder, self.recycle_bin_folder):
                managed_folder.mkdir(parents=True, exist_ok=True)
                for child in managed_folder.iterdir():
                    try:
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                    except Exception:
                        pass

            # Clear all CSV tables
            for table in ("projects", "files", "change_log", "todos", "item_inventory"):
                self.csv.write_rows(table, [])
            self.selected_project = None
            self.selected_file = None
            self.current_folder_rel = ""
            self.selected_item_kind = ""
            self.selected_item_rel = ""
            self.pending_file_operation = None
            self.projects = []
            self.tracked_files = []
            self.project_todos.clear()
            self.refresh_projects()
            self.refresh_files()
            self.history_text.config(state="normal")
            self.history_text.delete("1.0", tk.END)
            self.history_text.config(state="disabled")
            self.todo_listbox.delete(0, tk.END)
            messagebox.showinfo("Reset complete", f"Data reset complete. Auto backup saved to:\n{backup_dir}")

        ttk.Button(button_frame, text="Reset", command=do_reset).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=confirm_dialog.destroy).pack(side="left")
        confirm_dialog.wait_window()

    def on_project_select(self, event: object) -> None:
        previous_project_id = self.selected_project.project_id if self.selected_project else ""
        selection = self.project_tree.selection()
        if not selection:
            self.selected_project = None
            self.current_folder_rel = ""
            self.pending_file_operation = None
            self._update_file_action_buttons_state()
            return
        project_id = selection[0]
        self.selected_project = next((p for p in self.projects if p.project_id == project_id), None)
        if self.pending_file_operation and self.pending_file_operation.get("project_id") != project_id:
            self.pending_file_operation = None
        if self.selected_project:
            if previous_project_id != project_id:
                self.current_folder_rel = ""
            self._sync_untracked_files()
            self._load_project_todos()
            self._update_file_action_buttons_state()
        self.refresh_files()
        self._show_history()

    def _clear_section_selections(self, active_section: str) -> None:
        if active_section != "files":
            self.file_tree.selection_remove(self.file_tree.selection())
        if active_section != "todos":
            self.todo_listbox.selection_clear(0, tk.END)

    def _project_tree_click(self, event: tk.Event) -> None:
        self._clear_section_selections("projects")

    def _file_tree_click(self, event: tk.Event) -> None:
        self._clear_section_selections("files")

    def _file_tree_ctrl_click(self, event: tk.Event) -> str | None:
        self._clear_section_selections("files")
        item_id = self.file_tree.identify_row(event.y)
        if not item_id:
            return None
        selected = set(self.file_tree.selection())
        if item_id in selected:
            self.file_tree.selection_remove(item_id)
        else:
            self.file_tree.selection_add(item_id)
            self.file_tree.focus(item_id)
        self.on_file_select(None)
        return "break"

    def _file_tree_shift_click(self, event: tk.Event) -> str | None:
        self._clear_section_selections("files")
        item_id = self.file_tree.identify_row(event.y)
        if not item_id:
            return None
        # Shift-click on an already selected item toggles it off.
        if item_id in self.file_tree.selection():
            self.file_tree.selection_remove(item_id)
            self.on_file_select(None)
            return "break"
        return None

    def toggle_project_pin(self) -> None:
        if not self.selected_project:
            return
        project_rows = self.csv.read_rows("projects")
        for row in project_rows:
            if row.get("project_id") == self.selected_project.project_id:
                row["pinned"] = "0" if row.get("pinned", "0") == "1" else "1"
                self.selected_project.pinned = row["pinned"]
                break
        self.csv.write_rows("projects", project_rows)
        self.refresh_projects()

    def add_project(self) -> None:
        form = tk.Toplevel(self.root)
        form.title("Add Project")
        form.transient(self.root)
        form.grab_set()
        form.geometry("520x260")

        ttk.Label(form, text="Project Name:").pack(anchor="w", padx=12, pady=(12, 4))
        name_entry = ttk.Entry(form)
        name_entry.pack(fill="x", padx=12)
        name_entry.focus_set()

        ttk.Label(form, text="Short Description:").pack(anchor="w", padx=12, pady=(10, 4))
        description_entry = ttk.Entry(form)
        description_entry.pack(fill="x", padx=12)

        ttk.Label(form, text="Comma-separated Tags:").pack(anchor="w", padx=12, pady=(10, 4))
        tags_entry = ttk.Entry(form)
        tags_entry.pack(fill="x", padx=12)

        button_frame = ttk.Frame(form)
        button_frame.pack(fill="x", padx=12, pady=(14, 12))

        def save_project() -> None:
            project_name = name_entry.get().strip()
            if not project_name:
                messagebox.showwarning("Missing name", "Please enter a project name.", parent=form)
                return
            folder_path = self.repository_folder / project_name
            if folder_path.exists():
                messagebox.showwarning("Already exists", f"A folder named '{project_name}' already exists in the repository.", parent=form)
                return
            folder_path.mkdir(parents=True)
            description = description_entry.get().strip()
            tags = tags_entry.get().strip()
            project_id = self.csv.next_id("projects", "project_id")
            project = Project(
                project_id=project_id,
                project_name=project_name,
                root_path=str(folder_path),
                description=description,
                tags=tags,
                pinned="0",
                created_date=datetime.now().isoformat(),
                last_scanned_date="",
            )
            self.csv.append_row("projects", project.to_dict())
            self.refresh_projects()
            self.project_tree.selection_set(project_id)
            self.on_project_select(None)
            form.destroy()

        ttk.Button(button_frame, text="Save", command=save_project).pack(side="right")
        ttk.Button(button_frame, text="Cancel", command=form.destroy).pack(side="right", padx=(0, 8))
        form.wait_window()

    def add_files(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        self.refresh_files()
        initial_dir = Path(self.selected_project.root_path)
        selected = filedialog.askopenfilenames(
            title="Select files to track",
            initialdir=initial_dir,
        )
        if not selected:
            return
        for path_str in selected:
            source_path = Path(path_str).resolve()
            try:
                relative = source_path.relative_to(initial_dir)
            except ValueError:
                relative = None

            destination_path = self._copy_file_to_project(source_path, initial_dir)
            if destination_path is None:
                continue

            if relative is not None:
                relative_path = str(relative).replace("\\", "/")
            else:
                relative_path = destination_path.name

            if any(file.relative_path == relative_path for file in self.tracked_files):
                continue

            checksum = compute_checksum(destination_path)
            tracked = TrackedFile(
                file_id=self.csv.next_id("files", "file_id"),
                project_id=self.selected_project.project_id,
                relative_path=relative_path,
                extension=destination_path.suffix.lower(),
                file_size=destination_path.stat().st_size,
                last_modified=datetime.fromtimestamp(destination_path.stat().st_mtime).isoformat(),
                checksum=checksum,
                notes="",
            )
            self.csv.append_row("files", tracked.to_dict())
            self._save_snapshot_for_file(self.selected_project.project_id, destination_path, relative_path)
        self.refresh_files()

    def add_folder(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        project_root = Path(self.selected_project.root_path).resolve()
        selected_folder = filedialog.askdirectory(
            title="Select folder to add",
            initialdir=project_root,
        )
        if not selected_folder:
            return

        source_folder = Path(selected_folder).resolve()
        if not source_folder.exists() or not source_folder.is_dir():
            messagebox.showerror("Invalid folder", "Selected folder does not exist.")
            return

        # If folder is already inside the project, just sync tracking.
        try:
            source_folder.relative_to(project_root)
            self._sync_untracked_files()
            self.refresh_files()
            return
        except ValueError:
            pass

        destination_folder = project_root / source_folder.name
        if destination_folder.exists():
            overwrite = messagebox.askyesno(
                "Folder exists",
                f"The folder '{source_folder.name}' already exists in this project. Overwrite it?",
            )
            if not overwrite:
                return
            try:
                shutil.rmtree(destination_folder)
            except Exception as exc:
                messagebox.showerror("Copy failed", f"Could not replace existing folder: {exc}")
                return

        try:
            self._set_busy(True, "Copying folder contents...")
            shutil.copytree(source_folder, destination_folder)
            self._sync_untracked_files()
            self.refresh_files()
        except Exception as exc:
            messagebox.showerror("Copy failed", f"Unable to add folder: {exc}")
            return
        finally:
            self._set_busy(False)

    def _copy_file_to_project(self, source_path: Path, project_root: Path) -> Optional[Path]:
        destination = project_root / source_path.name
        if destination.exists():
            if destination.samefile(source_path):
                return destination
            if messagebox.askyesno(
                "Overwrite file?",
                f"The file {destination.name} already exists in the project folder. Overwrite?",
            ):
                destination.unlink()
            else:
                return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("rb") as reader, destination.open("wb") as writer:
            while True:
                chunk = reader.read(8192)
                if not chunk:
                    break
                writer.write(chunk)
        return destination

    def _sync_untracked_files(self) -> None:
        if not self.selected_project:
            return
        project_root = Path(self.selected_project.root_path)
        if not project_root.exists():
            return
        scanned = list(scan_project_files(project_root))
        tracked_paths = {row["relative_path"] for row in self.csv.read_rows("files") if row.get("project_id") == self.selected_project.project_id}
        for row in scanned:
            rel_path = row["relative_path"]
            if rel_path not in tracked_paths:
                file_id = self.csv.next_id("files", "file_id")
                tracked = TrackedFile(
                    file_id=file_id,
                    project_id=self.selected_project.project_id,
                    relative_path=rel_path,
                    extension=row["extension"],
                    file_size=int(row["file_size"]),
                    last_modified=row["last_modified"],
                    checksum=row["checksum"],
                    notes="",
                )
                self.csv.append_row("files", tracked.to_dict())
                file_path = project_root / Path(rel_path)
                if file_path.exists():
                    self._save_snapshot_for_file(self.selected_project.project_id, file_path, rel_path)
                record = ChangeRecord(
                    timestamp=datetime.now().isoformat(),
                    project_id=self.selected_project.project_id,
                    file_id=file_id,
                    change_type="ADD",
                    old_value="",
                    new_value=rel_path,
                    note="Manually added file discovered during refresh.",
                )
                self.csv.append_row("change_log", record.to_dict())

    def refresh_files(self) -> None:
        self.file_tree.delete(*self.file_tree.get_children())
        self.details_text.config(state="normal")
        self.details_text.delete("1.0", tk.END)
        self.details_text.config(state="disabled")
        if not self.selected_project:
            self._update_file_action_buttons_state()
            return
        self._sync_untracked_files()
        files = [TrackedFile.from_dict(row) for row in self.csv.read_rows("files") if row.get("project_id") == self.selected_project.project_id]
        self.tracked_files = files
        extensions = sorted({file.extension for file in files if file.extension})
        self.extension_combo['values'] = [""] + extensions
        selected_ext = self.extension_combo.get().strip().lower()
        search_terms = [term for term in self.search_entry.get().strip().lower().split() if term]
        note_filter = self.note_filter_entry.get().strip().lower()
        project_root = Path(self.selected_project.root_path).resolve()
        current_dir = project_root / Path(self.current_folder_rel) if self.current_folder_rel else project_root
        if not current_dir.exists() or not current_dir.is_dir():
            self.current_folder_rel = ""
            current_dir = project_root

        tracked_by_rel = {file.relative_path: file for file in files}
        note_matched_rel_paths: set[str] = set()
        if note_filter:
            note_matched_rel_paths = {
                file.relative_path
                for file in files
                if note_filter in (file.notes or "").lower()
            }

        for item_path in sorted(current_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            relative = str(item_path.relative_to(project_root)).replace("\\", "/")
            item_name = item_path.name

            if search_terms and not all(term in relative.lower() for term in search_terms):
                continue

            if item_path.is_dir():
                if note_filter:
                    folder_prefix = f"{relative}/"
                    has_matching_note_file = any(
                        rel_path.startswith(folder_prefix) for rel_path in note_matched_rel_paths
                    )
                    if not has_matching_note_file:
                        continue
                self.file_tree.insert("", "end", iid=f"folder::{relative}", text=item_name, image=self.tree_folder_icon, values=("", ""))
                continue

            tracked = tracked_by_rel.get(relative)
            extension = (tracked.extension if tracked else item_path.suffix.lower()) or ""
            if selected_ext and extension.lower() != selected_ext:
                continue
            if note_filter and (not tracked or note_filter not in (tracked.notes or "").lower()):
                continue
            file_size = tracked.file_size if tracked else item_path.stat().st_size
            modified = tracked.last_modified if tracked else datetime.fromtimestamp(item_path.stat().st_mtime).isoformat()
            formatted_modified = self._format_datetime_readable(modified)
            self.file_tree.insert(
                "",
                "end",
                iid=f"file::{relative}",
                text=item_name,
                image=self._icon_for_extension(extension),
                values=(file_size, formatted_modified),
            )
        self.selected_file = None
        self.selected_item_kind = ""
        self.selected_item_rel = ""
        breadcrumb = f"/{self.current_folder_rel}" if self.current_folder_rel else "/"
        self.breadcrumb_label.config(text=f"Path: {breadcrumb}")
        self._update_file_action_buttons_state()

    def on_file_select(self, event: object) -> None:
        selection = self.file_tree.selection()
        if not selection or not self.selected_project:
            self.selected_file = None
            self.selected_item_kind = ""
            self.selected_item_rel = ""
            return
        if len(selection) == 1:
            selected_iid = selection[0]
            if selected_iid.startswith("file::"):
                relative = selected_iid.split("::", 1)[1]
                self.selected_item_kind = "file"
                self.selected_item_rel = relative
                self.selected_file = next((f for f in self.tracked_files if f.relative_path == relative), None)
                self._show_file_details()
                self._show_history()
            else:
                self.selected_item_kind = "folder"
                self.selected_item_rel = selected_iid.split("::", 1)[1]
                self.selected_file = None
                self.details_text.config(state="normal")
                self.details_text.delete("1.0", tk.END)
                self.details_text.insert(tk.END, f"Folder: {self.selected_item_rel}\n")
                self.details_text.config(state="disabled")
                self._show_history()
        else:
            self.selected_file = None
            self.selected_item_kind = ""
            self.selected_item_rel = ""
            self.details_text.config(state="normal")
            self.details_text.delete("1.0", tk.END)
            self.details_text.config(state="disabled")
            self.history_text.config(state="normal")
            self.history_text.delete("1.0", tk.END)
            self.history_text.config(state="disabled")

    def on_project_tree_double_click(self, event: tk.Event) -> str | None:
        region = self.project_tree.identify_region(event.x, event.y)
        if region == "separator":
            self._reset_project_tree_columns_to_default()
            return "break"
        if region in {"heading", "cell"}:
            column_id = self.project_tree.identify_column(event.x)
            self._autofit_treeview_column(self.project_tree, column_id, min_width=60)
            return "break"
        return None

    def on_file_double_click(self, event: tk.Event) -> str | None:
        region = self.file_tree.identify_region(event.x, event.y)
        if region == "separator":
            self._reset_file_tree_columns_to_default()
            return "break"

        column_id = self.file_tree.identify_column(event.x)
        row_id = self.file_tree.identify_row(event.y)
        if row_id and column_id == "#0":
            self.file_tree.selection_set(row_id)
            self.on_file_select(event)
            if row_id.startswith("folder::"):
                self.current_folder_rel = row_id.split("::", 1)[1]
                self.refresh_files()
                return "break"
            if row_id.startswith("file::"):
                self.open_file()
                return "break"

        if region in {"heading", "cell", "tree"}:
            self._autofit_treeview_column(self.file_tree, column_id, min_width=70)
            return "break"
        return None

    def go_back_folder(self) -> None:
        if not self.current_folder_rel:
            return
        current = Path(self.current_folder_rel)
        parent = current.parent
        self.current_folder_rel = "" if str(parent) == "." else str(parent).replace("\\", "/")
        self.refresh_files()

    def _create_folder_icon(self, body_color: str, tab_color: str) -> tk.PhotoImage:
        icon = tk.PhotoImage(width=14, height=14)
        icon.put(body_color, to=(1, 5, 12, 12))
        icon.put(tab_color, to=(1, 3, 8, 6))
        icon.put("#b38a1e", to=(1, 5, 12, 5))
        return icon

    def _create_zip_folder_icon(self) -> tk.PhotoImage:
        icon = self._create_folder_icon("#d9b86b", "#c29c4f")
        # Zipper teeth in the center for compressed archives.
        icon.put("#616161", to=(6, 5, 7, 12))
        icon.put("#f5f5f5", to=(6, 6, 7, 6))
        icon.put("#f5f5f5", to=(6, 8, 7, 8))
        icon.put("#f5f5f5", to=(6, 10, 7, 10))
        return icon

    def _create_file_icon(self, accent_color: str, style: str) -> tk.PhotoImage:
        icon = tk.PhotoImage(width=14, height=14)
        icon.put("#f8f9fa", to=(2, 1, 11, 12))
        icon.put("#b0b0b0", to=(2, 1, 11, 1))
        icon.put("#b0b0b0", to=(2, 12, 11, 12))
        icon.put("#b0b0b0", to=(2, 1, 2, 12))
        icon.put("#b0b0b0", to=(11, 1, 11, 12))
        icon.put("#e9ecef", to=(9, 1, 11, 3))
        icon.put("#c7c7c7", to=(9, 3, 11, 3))
        icon.put(accent_color, to=(3, 3, 8, 4))

        if style == "text":
            icon.put("#6c757d", to=(3, 6, 10, 6))
            icon.put("#6c757d", to=(3, 8, 10, 8))
            icon.put("#6c757d", to=(3, 10, 9, 10))
        elif style == "markdown":
            icon.put("#1d3557", to=(3, 6, 10, 6))
            icon.put("#1d3557", to=(3, 7, 4, 10))
            icon.put("#1d3557", to=(6, 7, 7, 10))
            icon.put("#1d3557", to=(9, 7, 10, 10))
        elif style == "doc":
            icon.put("#1565c0", to=(3, 6, 4, 10))
            icon.put("#1565c0", to=(5, 6, 9, 6))
            icon.put("#1565c0", to=(5, 8, 9, 8))
            icon.put("#1565c0", to=(5, 10, 9, 10))
        elif style == "sheet":
            icon.put("#2e7d32", to=(3, 6, 10, 10))
            icon.put("#e8f5e9", to=(4, 7, 9, 9))
            icon.put("#2e7d32", to=(6, 7, 6, 9))
            icon.put("#2e7d32", to=(4, 8, 9, 8))
        elif style == "slide":
            icon.put("#ef6c00", to=(3, 6, 10, 10))
            icon.put("#fff3e0", to=(4, 7, 9, 9))
            icon.put("#ef6c00", to=(4, 10, 9, 10))
        elif style == "python":
            icon.put("#306998", to=(3, 6, 7, 8))
            icon.put("#ffd43b", to=(6, 8, 10, 10))
        elif style == "pdf":
            icon.put("#d62828", to=(3, 6, 10, 10))
            icon.put("#ffffff", to=(5, 7, 8, 9))
        elif style == "image":
            icon.put("#e9c46a", to=(3, 10, 10, 10))
            icon.put("#2a9d8f", to=(4, 8, 6, 10))
            icon.put("#264653", to=(6, 7, 10, 10))
        elif style == "audio":
            icon.put("#6a4c93", to=(4, 6, 4, 10))
            icon.put("#6a4c93", to=(6, 7, 6, 9))
            icon.put("#6a4c93", to=(8, 6, 8, 10))
        elif style == "video":
            icon.put("#9c27b0", to=(3, 6, 10, 10))
            icon.put("#ffffff", to=(6, 7, 7, 9))
            icon.put("#ffffff", to=(8, 8, 8, 8))
        elif style == "csv":
            icon.put("#2f9e44", to=(3, 6, 10, 10))
            icon.put("#e8f5e9", to=(4, 7, 9, 9))
            icon.put("#2f9e44", to=(6, 7, 6, 9))
            icon.put("#2f9e44", to=(4, 8, 9, 8))
        elif style == "json":
            icon.put("#f08c00", to=(4, 6, 4, 10))
            icon.put("#f08c00", to=(9, 6, 9, 10))
            icon.put("#f08c00", to=(6, 7, 7, 9))
        elif style == "xml":
            icon.put("#c77dff", to=(4, 8, 5, 8))
            icon.put("#c77dff", to=(8, 8, 9, 8))
            icon.put("#c77dff", to=(6, 6, 7, 10))
        else:
            icon.put("#9e9e9e", to=(3, 7, 10, 7))
            icon.put("#9e9e9e", to=(3, 9, 10, 9))
        return icon

    def _create_info_icon(self) -> tk.PhotoImage:
        icon = tk.PhotoImage(width=14, height=14)
        icon.put("#1f6feb", to=(1, 1, 12, 12))
        icon.put("#ffffff", to=(6, 3, 7, 3))
        icon.put("#ffffff", to=(6, 5, 7, 10))
        return icon

    def _create_gear_icon(self) -> tk.PhotoImage:
        icon = tk.PhotoImage(width=14, height=14)
        # Simple pixel gear: teeth plus center hub.
        gear_color = "#5f6368"
        hub_color = "#e8eaed"
        icon.put(gear_color, to=(5, 1, 8, 2))
        icon.put(gear_color, to=(5, 11, 8, 12))
        icon.put(gear_color, to=(1, 5, 2, 8))
        icon.put(gear_color, to=(11, 5, 12, 8))
        icon.put(gear_color, to=(3, 3, 4, 4))
        icon.put(gear_color, to=(9, 3, 10, 4))
        icon.put(gear_color, to=(3, 9, 4, 10))
        icon.put(gear_color, to=(9, 9, 10, 10))
        icon.put(gear_color, to=(4, 4, 9, 9))
        icon.put(hub_color, to=(6, 6, 7, 7))
        return icon

    def _icon_for_extension(self, extension: str) -> tk.PhotoImage:
        ext = extension.lower().strip()
        if ext in {".py", ".pyw"}:
            return self.tree_file_icons["python"]
        if ext in {".txt", ".log", ".ini", ".cfg", ".conf", ".yaml", ".yml"}:
            return self.tree_file_icons["text"]
        if ext in {".md", ".rst"}:
            return self.tree_file_icons["markdown"]
        if ext in {".csv", ".tsv"}:
            return self.tree_file_icons["csv"]
        if ext in {".json"}:
            return self.tree_file_icons["json"]
        if ext in {".xml", ".html", ".htm"}:
            return self.tree_file_icons["xml"]
        if ext in {".pdf"}:
            return self.tree_file_icons["pdf"]
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}:
            return self.tree_file_icons["image"]
        if ext in {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}:
            return self.tree_file_icons["archive"]
        if ext in {".doc", ".docx", ".odt"}:
            return self.tree_file_icons["doc"]
        if ext in {".xls", ".xlsx", ".ods"}:
            return self.tree_file_icons["sheet"]
        if ext in {".ppt", ".pptx", ".odp"}:
            return self.tree_file_icons["slide"]
        if ext in {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}:
            return self.tree_file_icons["audio"]
        if ext in {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".webm"}:
            return self.tree_file_icons["video"]
        return self.tree_file_icons["generic"]

    def _update_file_action_buttons_state(self) -> None:
        has_project = self.selected_project is not None
        if has_project:
            self.search_entry.state(["!disabled"])
            self.extension_combo.state(["!disabled", "readonly"])
            self.note_filter_entry.state(["!disabled"])
            self.add_files_button.state(["!disabled"])
            self.add_folder_button.state(["!disabled"])
            self.view_history_button.state(["!disabled"])
            self.add_note_button.state(["!disabled"])
            self.remove_note_button.state(["!disabled"])
            self.history_filter_combo.state(["!disabled", "readonly"])
        else:
            self.search_entry.state(["disabled"])
            self.extension_combo.state(["disabled"])
            self.note_filter_entry.state(["disabled"])
            self.add_files_button.state(["disabled"])
            self.add_folder_button.state(["disabled"])
            self.view_history_button.state(["disabled"])
            self.add_note_button.state(["disabled"])
            self.remove_note_button.state(["disabled"])
            self.history_filter_combo.state(["disabled"])

        if has_project and self.current_folder_rel:
            self.back_button.state(["!disabled"])
        else:
            self.back_button.state(["disabled"])

    def _show_file_details(self) -> None:
        self.details_text.config(state="normal")
        self.details_text.delete("1.0", tk.END)
        if not self.selected_file:
            self.details_text.config(state="disabled")
            return
        formatted_modified = self._format_datetime_readable(self.selected_file.last_modified)
        details = (
            f"File ID: {self.selected_file.file_id}\n"
            f"Relative Path: {self.selected_file.relative_path}\n"
            f"Extension: {self.selected_file.extension}\n"
            f"Size: {self.selected_file.file_size} bytes\n"
            f"Last Modified: {formatted_modified}\n"
            f"Checksum: {self.selected_file.checksum}\n"
            f"File Notes: {self.selected_file.notes}\n"
        )
        self.details_text.insert(tk.END, details)
        self.details_text.config(state="disabled")

    def _show_history(self) -> None:
        self.history_text.config(state="normal")
        self.history_text.delete("1.0", tk.END)
        if not self.selected_project:
            self.history_text.config(state="disabled")
            return
        change_rows = [row for row in self.csv.read_rows("change_log") if row.get("project_id") == self.selected_project.project_id]
        filter_type = self.history_filter_combo.get().strip().upper() if self.history_filter_combo.get() else "ALL"
        for row in change_rows[-50:]:
            if filter_type and filter_type != "ALL" and row.get("change_type", "").upper() != filter_type:
                continue
            timestamp = self._format_datetime_readable(row.get("timestamp", ""))
            entry = self._history_entry_text(row)
            self.history_text.insert(tk.END, f"{timestamp} | {entry}\n")
        self.history_text.config(state="disabled")
        self._show_project_todos()

    def _load_project_todos(self) -> None:
        if not self.selected_project:
            return
        todos = [row for row in self.csv.read_rows("todos") if row.get("project_id") == self.selected_project.project_id]
        self.project_todos[self.selected_project.project_id] = todos

    def _show_project_todos(self) -> None:
        self.todo_listbox.delete(0, tk.END)
        if not self.selected_project:
            return
        todos = self.project_todos.get(self.selected_project.project_id, [])
        for todo in todos:
            title = todo.get("title", "").strip() or todo.get("description", "")[:60]
            self.todo_listbox.insert(tk.END, title)

    def _note_popup(self, title_init: str = "", desc_init: str = "", read_only: bool = False, window_title: str = "Note") -> tuple[str, str] | None:
        """Display a title+content note form. In read_only mode shows Close/Edit buttons.
        Returns (title, description) tuple when saved, else None."""
        result: list[tuple[str, str] | None] = [None]

        dialog = tk.Toplevel(self.root)
        dialog.title(window_title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("540x320")
        dialog.minsize(400, 260)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(2, weight=1)

        ttk.Label(dialog, text="Title:").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 2))
        title_var = tk.StringVar(value=title_init)
        title_entry = ttk.Entry(dialog, textvariable=title_var)
        title_entry.grid(row=1, column=0, sticky="ew", padx=12)

        ttk.Label(dialog, text="Content:").grid(row=2, column=0, sticky="w", padx=12, pady=(8, 2))
        content_frame = ttk.Frame(dialog)
        content_frame.grid(row=3, column=0, sticky="nsew", padx=12)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)
        dialog.rowconfigure(3, weight=1)
        desc_text = tk.Text(content_frame, wrap="word", height=8)
        desc_text.grid(row=0, column=0, sticky="nsew")
        desc_sb = ttk.Scrollbar(content_frame, orient="vertical", command=desc_text.yview)
        desc_sb.grid(row=0, column=1, sticky="ns")
        desc_text.configure(yscrollcommand=desc_sb.set)
        desc_text.insert("1.0", desc_init)

        if read_only:
            title_entry.configure(state="disabled")
            desc_text.configure(state="disabled")

        btn_frame = ttk.Frame(dialog)
        btn_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(8, 12))

        if read_only:
            def do_edit() -> None:
                title_entry.configure(state="normal")
                desc_text.configure(state="normal")
                edit_btn.pack_forget()
                close_btn.pack_forget()
                save_btn.pack(side="right")
                cancel_btn.pack(side="right", padx=(0, 8))
                title_entry.focus_set()

            def do_save() -> None:
                t = title_var.get().strip()
                d = desc_text.get("1.0", tk.END).strip()
                if not t:
                    messagebox.showwarning("Note", "Title cannot be empty.", parent=dialog)
                    return
                result[0] = (t, d)
                dialog.destroy()

            edit_btn = ttk.Button(btn_frame, text="Edit", command=do_edit)
            edit_btn.pack(side="right")
            close_btn = ttk.Button(btn_frame, text="Close", command=dialog.destroy)
            close_btn.pack(side="right", padx=(0, 8))
            save_btn = ttk.Button(btn_frame, text="Save", command=do_save)
            cancel_btn = ttk.Button(btn_frame, text="Cancel", command=dialog.destroy)
        else:
            def do_save_new() -> None:
                t = title_var.get().strip()
                d = desc_text.get("1.0", tk.END).strip()
                if not t:
                    messagebox.showwarning("Note", "Title cannot be empty.", parent=dialog)
                    return
                result[0] = (t, d)
                dialog.destroy()

            ttk.Button(btn_frame, text="Save", command=do_save_new).pack(side="right")
            ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))
            title_entry.focus_set()

        dialog.wait_window()
        return result[0]

    def add_todo_item(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return

        res = self._note_popup(window_title=f"Add Note — {self.selected_project.project_name}")
        if res is None:
            return
        title, description = res
        todo_row = {
            "todo_id": self.csv.next_id("todos", "todo_id"),
            "project_id": self.selected_project.project_id,
            "title": title,
            "description": description,
            "created_date": datetime.now().isoformat(),
        }
        self.csv.append_row("todos", todo_row)
        change = ChangeRecord(
            timestamp=datetime.now().isoformat(),
            project_id=self.selected_project.project_id,
            file_id="",
            change_type="NOTE_ADD",
            old_value="",
            new_value=title,
            note=f"Project note added: {title}",
        )
        self.csv.append_row("change_log", change.to_dict())
        self._load_project_todos()
        self._show_project_todos()
        self._show_history()

    def remove_todo_item(self) -> None:
        if not self.selected_project:
            return
        selection = self.todo_listbox.curselection()
        if not selection:
            return
        todos = self.project_todos.get(self.selected_project.project_id, [])
        targets = [todos[i] for i in selection if 0 <= i < len(todos)]
        if not targets:
            return
        count = len(targets)
        if count > 1:
            if not messagebox.askyesno(
                "Remove Notes",
                f"You have {count} notes selected. Remove all {count} notes permanently?",
            ):
                return
        all_todos = self.csv.read_rows("todos")
        ids_to_remove = {t.get("todo_id") for t in targets}
        remaining = [
            row for row in all_todos
            if not (row.get("project_id") == self.selected_project.project_id and row.get("todo_id") in ids_to_remove)
        ]
        self.csv.write_rows("todos", remaining)
        for t in targets:
            removed_title = t.get("title", "") or t.get("description", "")[:60]
            change = ChangeRecord(
                timestamp=datetime.now().isoformat(),
                project_id=self.selected_project.project_id,
                file_id="",
                change_type="NOTE_REMOVE",
                old_value=removed_title,
                new_value="",
                note=f"Project note removed: {removed_title}",
            )
            self.csv.append_row("change_log", change.to_dict())
        self._load_project_todos()
        self._show_project_todos()
        self._show_history()

    def open_todo_item(self) -> None:
        """Open selected note(s) in a read-only popup with an Edit button."""
        if not self.selected_project:
            return
        selection = self.todo_listbox.curselection()
        if not selection:
            return
        todos = self.project_todos.get(self.selected_project.project_id, [])
        targets = [todos[i] for i in selection if 0 <= i < len(todos)]
        if not targets:
            return
        count = len(targets)
        if count > 1:
            if not messagebox.askyesno(
                "Open Notes",
                f"You have {count} notes selected. Each note will open one at a time. Continue?",
            ):
                return
        any_changed = False
        for todo in targets:
            todo_id = todo.get("todo_id")
            old_title = todo.get("title", "") or todo.get("description", "")[:60]
            res = self._note_popup(
                title_init=todo.get("title", ""),
                desc_init=todo.get("description", ""),
                read_only=True,
                window_title=f"Note — {old_title}",
            )
            if res is None:
                continue
            new_title, new_desc = res
            all_todos = self.csv.read_rows("todos")
            for row in all_todos:
                if row.get("project_id") == self.selected_project.project_id and row.get("todo_id") == todo_id:
                    row["title"] = new_title
                    row["description"] = new_desc
                    break
            self.csv.write_rows("todos", all_todos)
            change = ChangeRecord(
                timestamp=datetime.now().isoformat(),
                project_id=self.selected_project.project_id,
                file_id="",
                change_type="NOTE_EDIT",
                old_value=old_title,
                new_value=new_title,
                note=f"Project note edited: {new_title}",
            )
            self.csv.append_row("change_log", change.to_dict())
            any_changed = True
        if any_changed:
            self._load_project_todos()
            self._show_project_todos()
            self._show_history()

    def edit_todo_item(self) -> None:
        """Edit selected note directly (opens popup in edit mode)."""
        if not self.selected_project:
            return
        selection = self.todo_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        todos = self.project_todos.get(self.selected_project.project_id, [])
        if not (0 <= index < len(todos)):
            return
        todo = todos[index]
        todo_id = todo.get("todo_id")
        old_title = todo.get("title", "") or todo.get("description", "")[:60]
        res = self._note_popup(
            title_init=todo.get("title", ""),
            desc_init=todo.get("description", ""),
            read_only=False,
            window_title=f"Edit Note — {old_title}",
        )
        if res is None:
            return
        new_title, new_desc = res
        all_todos = self.csv.read_rows("todos")
        for row in all_todos:
            if row.get("project_id") == self.selected_project.project_id and row.get("todo_id") == todo_id:
                row["title"] = new_title
                row["description"] = new_desc
                break
        self.csv.write_rows("todos", all_todos)
        change = ChangeRecord(
            timestamp=datetime.now().isoformat(),
            project_id=self.selected_project.project_id,
            file_id="",
            change_type="NOTE_EDIT",
            old_value=old_title,
            new_value=new_title,
            note=f"Project note edited: {new_title}",
        )
        self.csv.append_row("change_log", change.to_dict())
        self._load_project_todos()
        self._show_project_todos()
        self._show_history()

    def _todo_listbox_click(self, event: tk.Event) -> str | None:
        """Preserve multi-selection when clicking an already-selected item."""
        self._clear_section_selections("todos")
        index = self.todo_listbox.nearest(event.y)
        if 0 <= index < self.todo_listbox.size() and index in self.todo_listbox.curselection():
            # Item already selected — don't let Tkinter reset the selection.
            self.todo_listbox.activate(index)
            return "break"
        return None

    def _todo_listbox_ctrl_click(self, event: tk.Event) -> str | None:
        self._clear_section_selections("todos")
        index = self.todo_listbox.nearest(event.y)
        if not (0 <= index < self.todo_listbox.size()):
            return None
        if self.todo_listbox.selection_includes(index):
            self.todo_listbox.selection_clear(index)
        else:
            self.todo_listbox.selection_set(index)
            self.todo_listbox.activate(index)
        self.todo_listbox.focus_set()
        return "break"

    def _todo_listbox_shift_click(self, event: tk.Event) -> str | None:
        self._clear_section_selections("todos")
        index = self.todo_listbox.nearest(event.y)
        if not (0 <= index < self.todo_listbox.size()):
            return None
        # Shift-click on an already selected item toggles it off.
        if self.todo_listbox.selection_includes(index):
            self.todo_listbox.selection_clear(index)
            self.todo_listbox.focus_set()
            return "break"
        return None

    def show_todo_context_menu(self, event: tk.Event) -> str | None:
        if not self.selected_project:
            return None
        index = self.todo_listbox.nearest(event.y)
        is_item_hit = False
        if 0 <= index < self.todo_listbox.size():
            row_bbox = self.todo_listbox.bbox(index)
            if row_bbox:
                row_top = row_bbox[1]
                row_height = row_bbox[3]
                is_item_hit = row_top <= event.y <= (row_top + row_height)

        if not is_item_hit:
            self.todo_listbox.selection_clear(0, tk.END)
            self.todo_listbox.focus_set()
            try:
                self.todo_empty_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.todo_empty_context_menu.grab_release()
            return "break"

        # If the right-clicked item is already part of the selection, keep
        # the full selection intact so the context menu acts on all of them.
        if index not in self.todo_listbox.curselection():
            self.todo_listbox.selection_clear(0, tk.END)
            self.todo_listbox.selection_set(index)
        self.todo_listbox.activate(index)
        self.todo_listbox.focus_set()
        try:
            self.todo_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.todo_context_menu.grab_release()
        return "break"

    def add_file_note(self) -> None:
        if not self.selected_project or not self.selected_file:
            return

        editor = tk.Toplevel(self.root)
        editor.title("Add/Edit File Notes")
        editor.transient(self.root)
        editor.grab_set()
        editor.geometry("600x320")

        ttk.Label(editor, text=f"File Notes for: {self.selected_file.relative_path}").pack(anchor="w", padx=10, pady=(10, 0))
        note_text = tk.Text(editor, wrap="word", width=72, height=12)
        note_text.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        note_text.insert("1.0", self.selected_file.notes or "")

        button_frame = ttk.Frame(editor)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))

        def save_note() -> None:
            note_value = note_text.get("1.0", tk.END).strip()
            file_rows = self.csv.read_rows("files")
            for row in file_rows:
                if row.get("file_id") == self.selected_file.file_id:
                    row["notes"] = note_value
                    self.selected_file.notes = note_value
                    break
            self.csv.write_rows("files", file_rows)
            change = ChangeRecord(
                timestamp=datetime.now().isoformat(),
                project_id=self.selected_project.project_id,
                file_id=self.selected_file.file_id,
                change_type="NOTE",
                old_value="",
                new_value=note_value,
                note="User-added note to tracked file.",
            )
            self.csv.append_row("change_log", change.to_dict())
            self._show_file_details()
            self._show_history()
            editor.destroy()

        ttk.Button(button_frame, text="Save", command=save_note).pack(side="right")
        ttk.Button(button_frame, text="Cancel", command=editor.destroy).pack(side="right", padx=(0, 8))
        editor.wait_window()

    def show_project_context_menu(self, event: object) -> None:
        project_id = self.project_tree.identify_row(event.y)
        if not project_id:
            try:
                self.project_empty_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.project_empty_context_menu.grab_release()
            return
        self.project_tree.selection_set(project_id)
        self.project_tree.focus(project_id)
        self.on_project_select(None)
        try:
            self.project_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.project_context_menu.grab_release()

    def show_file_context_menu(self, event: object) -> None:
        file_id = self.file_tree.identify_row(event.y)
        if not file_id:
            self._show_file_destination_menu(event)
            return
        if file_id not in self.file_tree.selection():
            self.file_tree.selection_set(file_id)
        self.file_tree.focus(file_id)
        self.on_file_select(None)
        try:
            self.file_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.file_context_menu.grab_release()

    def _show_file_destination_menu(self, event: object) -> None:
        if not self.selected_project:
            return

        self.file_destination_menu.delete(0, tk.END)

        if self.pending_file_operation and self.pending_file_operation.get("project_id") != self.selected_project.project_id:
            self.pending_file_operation = None

        if self.pending_file_operation:
            operation = str(self.pending_file_operation.get("operation", ""))
            if operation in {"copy", "move"}:
                label = "Copy Here" if operation == "copy" else "Move Here"
                self.file_destination_menu.add_command(label=label, command=self.paste_pending_items_here)
                self.file_destination_menu.add_separator()

        if self._selected_file_tree_items():
            self.file_destination_menu.add_command(label="Extract Selected Archives Here", command=self.extract_selected_archives_here)
            self.file_destination_menu.add_command(label="Compress Selected to ZIP...", command=self.compress_selected_items_to_zip)
            self.file_destination_menu.add_command(label="Compress Folder to ZIP", command=self.compress_selected_folders_to_zip)
            self.file_destination_menu.add_separator()

        self.file_destination_menu.add_command(label="Create New File...", command=self.create_new_file)
        self.file_destination_menu.add_command(label="Create New Folder...", command=self.create_new_folder)

        try:
            self.file_destination_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.file_destination_menu.grab_release()

    def create_new_file(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return

        project_root = Path(self.selected_project.root_path)
        target_dir = project_root / Path(self.current_folder_rel) if self.current_folder_rel else project_root
        form = tk.Toplevel(self.root)
        form.title("Create New File")
        form.transient(self.root)
        form.grab_set()
        form.geometry("560x190")

        ttk.Label(form, text="File name:").pack(anchor="w", padx=12, pady=(12, 4))
        name_entry = ttk.Entry(form)
        name_entry.pack(fill="x", padx=12)
        name_entry.focus_set()

        ttk.Label(form, text="Extension (example: txt or .txt):").pack(anchor="w", padx=12, pady=(10, 4))
        ext_entry = ttk.Entry(form)
        ext_entry.pack(fill="x", padx=12)
        location_text = f"Location: /{self.current_folder_rel}" if self.current_folder_rel else "Location: /"
        ttk.Label(form, text=location_text).pack(anchor="w", padx=12, pady=(10, 0))

        button_row = ttk.Frame(form)
        button_row.pack(fill="x", padx=12, pady=(14, 12))

        def create_file() -> None:
            base_name = name_entry.get().strip()
            ext = ext_entry.get().strip()

            if not base_name:
                messagebox.showwarning("Missing name", "Please enter a file name.", parent=form)
                return

            if ext and not ext.startswith("."):
                ext = f".{ext}"

            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / f"{base_name}{ext}"

            if target_path.exists():
                messagebox.showwarning("Already exists", "A file with that name already exists in the target folder.", parent=form)
                return

            try:
                target_path.touch()
            except Exception as exc:
                messagebox.showerror("Create failed", f"Could not create file: {exc}", parent=form)
                return

            relative = str(target_path.relative_to(project_root)).replace("\\", "/")
            tracked = TrackedFile(
                file_id=self.csv.next_id("files", "file_id"),
                project_id=self.selected_project.project_id,
                relative_path=relative,
                extension=target_path.suffix.lower(),
                file_size=target_path.stat().st_size,
                last_modified=datetime.fromtimestamp(target_path.stat().st_mtime).isoformat(),
                checksum=compute_checksum(target_path),
                notes="",
            )
            self.csv.append_row("files", tracked.to_dict())
            self.csv.append_row("change_log", ChangeRecord(
                timestamp=datetime.now().isoformat(),
                project_id=self.selected_project.project_id,
                file_id=tracked.file_id,
                change_type="ADD",
                old_value="",
                new_value=relative,
                note="Created new file from context menu.",
            ).to_dict())
            self._save_snapshot_for_file(self.selected_project.project_id, target_path, relative)
            self.refresh_files()
            self._show_history()
            form.destroy()

        ttk.Button(button_row, text="Create", command=create_file).pack(side="right")
        ttk.Button(button_row, text="Cancel", command=form.destroy).pack(side="right", padx=(0, 8))
        form.wait_window()

    def create_new_folder(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return

        project_root = Path(self.selected_project.root_path)
        target_parent = project_root / Path(self.current_folder_rel) if self.current_folder_rel else project_root

        form = tk.Toplevel(self.root)
        form.title("Create New Folder")
        form.transient(self.root)
        form.grab_set()
        form.geometry("560x170")

        ttk.Label(form, text="Folder name:").pack(anchor="w", padx=12, pady=(12, 4))
        folder_name_entry = ttk.Entry(form)
        folder_name_entry.pack(fill="x", padx=12)
        folder_name_entry.focus_set()

        location_text = f"Location: /{self.current_folder_rel}" if self.current_folder_rel else "Location: /"
        ttk.Label(form, text=location_text).pack(anchor="w", padx=12, pady=(10, 0))

        button_row = ttk.Frame(form)
        button_row.pack(fill="x", padx=12, pady=(14, 12))

        def create_folder() -> None:
            folder_name = folder_name_entry.get().strip()
            if not folder_name:
                messagebox.showwarning("Missing name", "Please enter a folder name.", parent=form)
                return
            if any(char in folder_name for char in "\\/:*?\"<>|"):
                messagebox.showwarning("Invalid name", "Folder name contains invalid characters.", parent=form)
                return

            folder_path = target_parent / folder_name
            if folder_path.exists():
                messagebox.showwarning("Already exists", "A folder with that name already exists.", parent=form)
                return

            try:
                folder_path.mkdir(parents=True, exist_ok=False)
            except Exception as exc:
                messagebox.showerror("Create failed", f"Could not create folder: {exc}", parent=form)
                return

            relative = str(folder_path.relative_to(project_root)).replace("\\", "/")
            self.csv.append_row("change_log", ChangeRecord(
                timestamp=datetime.now().isoformat(),
                project_id=self.selected_project.project_id,
                file_id="",
                change_type="META_UPDATE",
                old_value="",
                new_value=relative,
                note="Created new folder from context menu.",
            ).to_dict())

            self.refresh_files()
            self._show_history()
            form.destroy()

        ttk.Button(button_row, text="Create", command=create_folder).pack(side="right")
        ttk.Button(button_row, text="Cancel", command=form.destroy).pack(side="right", padx=(0, 8))
        form.wait_window()

    def _selected_file_tree_items(self) -> List[tuple[str, str]]:
        items: List[tuple[str, str]] = []
        for item in self.file_tree.selection():
            if "::" not in item:
                continue
            kind, relative_path = item.split("::", 1)
            if kind in {"file", "folder"}:
                items.append((kind, relative_path))
        return items

    def _current_project_directory(self) -> Optional[Path]:
        if not self.selected_project:
            return None
        project_root = Path(self.selected_project.root_path)
        return project_root / Path(self.current_folder_rel) if self.current_folder_rel else project_root

    def _safe_extract_zip(self, archive: zipfile.ZipFile, destination: Path) -> None:
        destination_resolved = destination.resolve()
        for member in archive.infolist():
            member_path = destination / member.filename
            resolved_member = member_path.resolve()
            if resolved_member != destination_resolved and destination_resolved not in resolved_member.parents:
                raise RuntimeError(f"Unsafe archive entry detected: {member.filename}")
        archive.extractall(destination)

    def extract_selected_archives_here(self) -> None:
        if not self.selected_project:
            return
        destination_dir = self._current_project_directory()
        if destination_dir is None:
            return

        archive_exts = {".zip"}
        project_root = Path(self.selected_project.root_path)
        selected = self._selected_file_tree_items()
        archives: List[Path] = []
        for kind, rel in selected:
            if kind != "file":
                continue
            source = project_root / Path(rel)
            if source.suffix.lower() in archive_exts and source.exists() and source.is_file():
                archives.append(source)

        if not archives:
            messagebox.showwarning("Extract", "Select one or more ZIP files to extract.")
            return

        try:
            self._set_busy(True, "Extracting archives...")
            for archive_path in archives:
                with zipfile.ZipFile(archive_path, "r") as archive:
                    self._safe_extract_zip(archive, destination_dir)
            self.refresh_files()
            self._show_history()
            messagebox.showinfo("Extract", f"Extracted {len(archives)} archive(s) to:\n{destination_dir}")
        except Exception as exc:
            messagebox.showerror("Extract", f"Could not extract archive(s): {exc}")
        finally:
            self._set_busy(False)

    def compress_selected_items_to_zip(self) -> None:
        if not self.selected_project:
            return

        selected_items = self._selected_file_tree_items()
        if not selected_items:
            messagebox.showwarning("Compress", "Select one or more files or folders to compress.")
            return

        destination_dir = self._current_project_directory()
        if destination_dir is None:
            return

        archive_name = simpledialog.askstring(
            "Compress Selected",
            "ZIP file name (without .zip):",
            parent=self.root,
        )
        if archive_name is None:
            return
        archive_name = archive_name.strip()
        if not archive_name:
            messagebox.showwarning("Compress", "Please provide a ZIP name.")
            return
        if archive_name.lower().endswith(".zip"):
            archive_name = archive_name[:-4]
        if any(char in archive_name for char in "\\/:*?\"<>|"):
            messagebox.showwarning("Compress", "ZIP name contains invalid characters.")
            return

        destination_zip = destination_dir / f"{archive_name}.zip"
        if destination_zip.exists() and not messagebox.askyesno("Compress", f"{destination_zip.name} already exists. Overwrite?"):
            return

        project_root = Path(self.selected_project.root_path)
        try:
            self._set_busy(True, "Compressing selected items...")
            with zipfile.ZipFile(destination_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                for kind, rel in selected_items:
                    source = project_root / Path(rel)
                    if not source.exists():
                        continue
                    if kind == "file" and source.is_file():
                        archive.write(source, arcname=source.name)
                        continue
                    if kind == "folder" and source.is_dir():
                        for child in source.rglob("*"):
                            if child.is_file():
                                arcname = str(child.relative_to(source.parent)).replace("\\", "/")
                                archive.write(child, arcname=arcname)
            self.refresh_files()
            self._show_history()
            messagebox.showinfo("Compress", f"Created archive:\n{destination_zip}")
        except Exception as exc:
            messagebox.showerror("Compress", f"Could not compress selected items: {exc}")
        finally:
            self._set_busy(False)

    def compress_selected_folders_to_zip(self) -> None:
        if not self.selected_project:
            return

        selected_items = self._selected_file_tree_items()
        folder_rels = [rel for kind, rel in selected_items if kind == "folder"]
        if not folder_rels:
            messagebox.showwarning("Compress Folder", "Select one or more folders to compress.")
            return

        project_root = Path(self.selected_project.root_path)
        created_count = 0
        try:
            self._set_busy(True, "Compressing folder(s)...")
            for rel in folder_rels:
                folder_path = project_root / Path(rel)
                if not folder_path.exists() or not folder_path.is_dir():
                    continue
                zip_path = folder_path.with_suffix(".zip")
                if zip_path.exists() and not messagebox.askyesno(
                    "Compress Folder",
                    f"{zip_path.name} already exists. Overwrite?",
                ):
                    continue
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for child in folder_path.rglob("*"):
                        if child.is_file():
                            arcname = str(child.relative_to(folder_path.parent)).replace("\\", "/")
                            archive.write(child, arcname=arcname)
                created_count += 1

            self.refresh_files()
            self._show_history()
            if created_count:
                messagebox.showinfo("Compress Folder", f"Created {created_count} ZIP archive(s).")
            else:
                messagebox.showwarning("Compress Folder", "No folders were compressed.")
        except Exception as exc:
            messagebox.showerror("Compress Folder", f"Could not compress folder(s): {exc}")
        finally:
            self._set_busy(False)

    def _queue_file_operation(self, operation: str) -> None:
        if not self.selected_project:
            return
        items = self._selected_file_tree_items()
        if not items:
            messagebox.showwarning("Select items", "Please select one or more files or folders.")
            return
        self.pending_file_operation = {
            "operation": operation,
            "project_id": self.selected_project.project_id,
            "items": items,
        }

    def copy_selected_items(self) -> None:
        self._queue_file_operation("copy")

    def move_selected_items(self) -> None:
        self._queue_file_operation("move")

    def paste_pending_items_here(self) -> None:
        if not self.selected_project or not self.pending_file_operation:
            return
        if self.pending_file_operation.get("project_id") != self.selected_project.project_id:
            messagebox.showwarning("Paste items", "The queued items belong to a different project.")
            self.pending_file_operation = None
            return

        project_root = Path(self.selected_project.root_path)
        destination_dir = project_root / Path(self.current_folder_rel) if self.current_folder_rel else project_root
        destination_dir.mkdir(parents=True, exist_ok=True)

        operation = str(self.pending_file_operation.get("operation", ""))
        items = list(self.pending_file_operation.get("items", []))
        completed = 0
        skipped: List[str] = []
        undo_items: List[dict[str, str]] = []

        for kind, relative_path in items:
            source_path = project_root / Path(relative_path)
            if not source_path.exists():
                skipped.append(f"Missing source: {relative_path}")
                continue

            target_path = destination_dir / source_path.name
            if target_path.exists():
                skipped.append(f"Already exists: {target_path.name}")
                continue
            if target_path == source_path:
                skipped.append(f"Same destination: {relative_path}")
                continue
            if kind == "folder":
                try:
                    target_path.relative_to(source_path)
                    skipped.append(f"Cannot place folder inside itself: {relative_path}")
                    continue
                except ValueError:
                    pass

            try:
                if kind == "folder":
                    if operation == "copy":
                        shutil.copytree(source_path, target_path)
                    else:
                        shutil.move(str(source_path), str(target_path))
                else:
                    if operation == "copy":
                        shutil.copy2(source_path, target_path)
                    else:
                        shutil.move(str(source_path), str(target_path))
                if operation == "copy":
                    undo_items.append({
                        "operation": "copy",
                        "kind": kind,
                        "target": str(target_path),
                    })
                else:
                    undo_items.append({
                        "operation": "move",
                        "kind": kind,
                        "source": str(source_path),
                        "target": str(target_path),
                    })
                completed += 1
            except Exception as exc:
                skipped.append(f"{relative_path}: {exc}")

        if completed:
            if operation == "move":
                self.pending_file_operation = None
            if undo_items:
                self.undo_stack.append({
                    "type": "paste",
                    "project_id": self.selected_project.project_id,
                    "items": undo_items,
                })
            self.refresh_repository()

        if skipped:
            messagebox.showwarning("Paste items", "Some items were skipped:\n\n" + "\n".join(skipped[:10]))

    # Extensions that can be meaningfully diffed as plain text
    _TEXT_DIFFABLE_EXTENSIONS = {
        ".txt", ".log", ".md", ".rst", ".csv", ".tsv",
        ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx",
        ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp",
        ".cs", ".java", ".kt", ".go", ".rs", ".rb",
        ".php", ".swift", ".m", ".r", ".scala", ".lua",
        ".sh", ".bat", ".ps1", ".bash", ".zsh",
        ".json", ".yaml", ".yml", ".xml", ".html",
        ".htm", ".css", ".scss", ".less", ".sql",
        ".toml", ".ini", ".cfg", ".conf", ".env",
        ".dockerfile", ".makefile", ".gitignore",
    }

    def compare_to_previous_revision(self) -> None:
        if not self.selected_project or not self.selected_file:
            return
        current_file = Path(self.selected_project.root_path) / Path(self.selected_file.relative_path)
        if not current_file.exists() or not current_file.is_file():
            messagebox.showerror("Compare", "The selected file does not exist on disk.")
            return
        self._save_snapshot_for_file(
            self.selected_project.project_id,
            current_file,
            self.selected_file.relative_path,
        )
        snapshots = self._list_snapshots_for_relative(
            self.selected_project.project_id, self.selected_file.relative_path
        )
        if len(snapshots) < 2:
            messagebox.showinfo("Compare", "Not enough revisions to compare. Save more changes first.")
            return

        prev_snapshot = snapshots[-2]
        ext = Path(self.selected_file.relative_path).suffix.lower()
        is_text = ext in self._TEXT_DIFFABLE_EXTENSIONS or ext == ""

        # Build the comparison window
        win = tk.Toplevel(self.root)
        win.title(f"Compare Revision \u2014 {Path(self.selected_file.relative_path).name}")
        win.geometry("980x680")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        # ── Header bar ──────────────────────────────────────────────────────
        header = ttk.Frame(win, padding=(8, 4))
        header.grid(row=0, column=0, sticky="ew")
        prev_stat = prev_snapshot.stat()
        curr_stat = current_file.stat() if current_file.exists() else None
        prev_label = f"Previous  ({self._format_datetime_readable(datetime.fromtimestamp(prev_stat.st_mtime).isoformat())}  {prev_stat.st_size:,} B)"
        curr_label = (
            f"Current  ({self._format_datetime_readable(datetime.fromtimestamp(curr_stat.st_mtime).isoformat())}  {curr_stat.st_size:,} B)"
            if curr_stat else "Current  (missing)"
        )
        ttk.Label(header, text=prev_label, font=("TkFixedFont", 8), foreground="#555").pack(side="left", padx=(0, 20))
        ttk.Label(header, text=curr_label, font=("TkFixedFont", 8), foreground="#555").pack(side="left")

        if not is_text:
            # ── Unsupported binary / special file ───────────────────────────
            info_frame = ttk.Frame(win, padding=20)
            info_frame.grid(row=1, column=0, sticky="nsew")
            ttk.Label(
                info_frame,
                text=f"Side-by-side text comparison is not supported for '{ext or 'no extension'}' files.",
                font=("TkDefaultFont", 10, "bold"),
                foreground="#b71c1c",
            ).pack(anchor="w", pady=(0, 12))
            details = (
                f"File: {self.selected_file.relative_path}\n"
                f"Extension: {ext or '(none)'}\n"
                f"Previous size: {prev_stat.st_size:,} bytes\n"
                f"Current size: {curr_stat.st_size:,} bytes\n" if curr_stat else ""
            )
            size_diff = (curr_stat.st_size - prev_stat.st_size) if curr_stat else None
            if size_diff is not None:
                sign = "+" if size_diff >= 0 else ""
                details += f"Size change: {sign}{size_diff:,} bytes\n"
            details += (
                f"Previous checksum: {prev_snapshot.stem.split('__')[-1] if '__' in prev_snapshot.stem else 'N/A'}\n"
                f"Current checksum: {self.selected_file.checksum}\n"
            )
            is_same = (prev_snapshot.stem.split('__')[-1] if '__' in prev_snapshot.stem else None) == self.selected_file.checksum
            details += f"Identical: {'Yes' if is_same else 'No'}\n"
            text_box = tk.Text(info_frame, wrap="word", height=14, state="normal", font=("TkFixedFont", 9))
            text_box.insert("1.0", details)
            text_box.config(state="disabled")
            text_box.pack(fill="both", expand=True)
            return

        # ── Load text content ────────────────────────────────────────────────
        try:
            previous_lines = prev_snapshot.read_text(encoding="utf-8", errors="replace").splitlines()
            current_lines = current_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:
            messagebox.showerror("Compare", f"Could not read file contents: {exc}", parent=win)
            win.destroy()
            return

        diff_lines = list(difflib.unified_diff(
            previous_lines, current_lines,
            fromfile="previous", tofile="current",
            lineterm="",
        ))

        # ── Summary strip ────────────────────────────────────────────────────
        added   = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
        unchanged = len(current_lines) - added
        summary_frame = ttk.Frame(win, padding=(8, 2))
        summary_frame.grid(row=0, column=0, sticky="ew")
        prev_label_text = f"Previous  ({self._format_datetime_readable(datetime.fromtimestamp(prev_stat.st_mtime).isoformat())}  {prev_stat.st_size:,} B)"
        curr_label_text = (
            f"Current  ({self._format_datetime_readable(datetime.fromtimestamp(curr_stat.st_mtime).isoformat())}  {curr_stat.st_size:,} B)"
            if curr_stat else "Current  (missing)"
        )
        ttk.Label(summary_frame, text=prev_label_text, font=("TkFixedFont", 8), foreground="#555").pack(side="left", padx=(0, 16))
        ttk.Label(summary_frame, text=curr_label_text, font=("TkFixedFont", 8), foreground="#555").pack(side="left", padx=(0, 16))
        ttk.Label(summary_frame, text=f"+{added} added", font=("TkFixedFont", 8), foreground="#2e7d32").pack(side="left", padx=(0, 8))
        ttk.Label(summary_frame, text=f"-{removed} removed", font=("TkFixedFont", 8), foreground="#b71c1c").pack(side="left", padx=(0, 8))
        ttk.Label(summary_frame, text=f"{unchanged} unchanged" if not diff_lines else "", font=("TkFixedFont", 8), foreground="#555").pack(side="left")
        header.destroy()  # replace the placeholder header with the real summary

        # ── Diff text area with syntax colouring ─────────────────────────────
        win.rowconfigure(1, weight=1)
        text_frame = ttk.Frame(win)
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        diff_text = tk.Text(
            text_frame, wrap="none", font=("TkFixedFont", 9),
            state="normal", bg="#1e1e1e", fg="#d4d4d4",
            selectbackground="#264f78",
        )
        diff_text.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=diff_text.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(text_frame, orient="horizontal", command=diff_text.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        diff_text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        diff_text.tag_configure("added",   background="#1b3a1b", foreground="#89d185")
        diff_text.tag_configure("removed", background="#3a1b1b", foreground="#f14c4c")
        diff_text.tag_configure("header",  foreground="#569cd6", font=("TkFixedFont", 9, "bold"))
        diff_text.tag_configure("hunk",    foreground="#c586c0")

        if not diff_lines:
            diff_text.insert("end", "No differences detected. The files are identical.")
        else:
            for line in diff_lines:
                if line.startswith("++") or line.startswith("--"):
                    diff_text.insert("end", line + "\n", "header")
                elif line.startswith("@@"):
                    diff_text.insert("end", line + "\n", "hunk")
                elif line.startswith("+"):
                    diff_text.insert("end", line + "\n", "added")
                elif line.startswith("-"):
                    diff_text.insert("end", line + "\n", "removed")
                else:
                    diff_text.insert("end", line + "\n")
        diff_text.config(state="disabled")

    def restore_previous_revision(self) -> None:
        if not self.selected_project or not self.selected_file:
            return
        target_file = Path(self.selected_project.root_path) / Path(self.selected_file.relative_path)
        if target_file.exists() and target_file.is_file():
            self._save_snapshot_for_file(
                self.selected_project.project_id,
                target_file,
                self.selected_file.relative_path,
            )
        snapshots = self._list_snapshots_for_relative(self.selected_project.project_id, self.selected_file.relative_path)
        if len(snapshots) < 2:
            messagebox.showinfo("Restore", "No previous revision available.")
            return
        previous_snapshot = snapshots[-2]
        if not messagebox.askyesno("Restore", "Restore the previous revision for this file?"):
            return
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(previous_snapshot, target_file)
        except Exception as exc:
            messagebox.showerror("Restore failed", f"Could not restore revision: {exc}")
            return
        self.csv.append_row("change_log", ChangeRecord(
            timestamp=datetime.now().isoformat(),
            project_id=self.selected_project.project_id,
            file_id=self.selected_file.file_id,
            change_type="RESTORE",
            old_value="",
            new_value=self.selected_file.relative_path,
            note="Restored previous revision.",
        ).to_dict())
        self.refresh_repository()

    def _format_datetime_readable(self, timestamp: str) -> str:
        if not timestamp:
            return ""
        if isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp)
                return parsed.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                return timestamp.replace("T", " ")[:16]
        return str(timestamp)

    def _history_entry_text(self, row: dict) -> str:
        change_type = row.get("change_type", "UNKNOWN")
        old_value = row.get("old_value", "")
        new_value = row.get("new_value", "")
        note = row.get("note", "")
        file_id = row.get("file_id", "")

        if change_type == "ADD":
            if "discovered" in note.lower():
                return f"Added file '{new_value}' manually discovered during refresh."
            return f"Added file '{new_value}' via app."
        if change_type == "REMOVE":
            if "deleted" in note.lower():
                return f"Deleted file '{old_value}' via app."
            return f"Removed file '{old_value}'."
        if change_type == "MOVE":
            return f"Renamed file '{old_value}' to '{new_value}'."
        if change_type == "NOTE":
            return f"Note for file '{file_id}': {note}"
        if change_type == "META_UPDATE":
            return f"Metadata updated for '{new_value or old_value}': {note}"
        if change_type == "RESTORE":
            return f"Restored previous revision for '{new_value or old_value or file_id}'."
        return f"{change_type} for file '{new_value or old_value or file_id}': {note}"

    def _sort_treeview(self, tree: ttk.Treeview, col: str, reverse: bool) -> bool:
        if col == "path":
            items = [(self._tree_sort_key(tree.item(item, "text"), col), item) for item in tree.get_children("")]
        else:
            items = [(self._tree_sort_key(tree.set(item, col), col), item) for item in tree.get_children("")]
        items.sort(key=lambda x: x[0], reverse=reverse)
        for index, (_, item) in enumerate(items):
            tree.move(item, "", index)
        return not reverse

    def _tree_sort_key(self, value: str, col: str):
        if col == "size":
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        if col == "modified":
            try:
                return datetime.fromisoformat(value)
            except (ValueError, TypeError):
                return value.lower()
        return value.lower() if isinstance(value, str) else value

    def _sort_project_tree(self, col: str) -> None:
        self.sort_state["projects"][col] = self._sort_treeview(self.project_tree, col, self.sort_state["projects"][col])

    def _sort_file_tree(self, col: str) -> None:
        self.sort_state["files"][col] = self._sort_treeview(self.file_tree, col, self.sort_state["files"][col])

    def print_project_history(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        history_lines = []
        change_rows = [row for row in self.csv.read_rows("change_log") if row.get("project_id") == self.selected_project.project_id]
        for row in change_rows:
            timestamp = self._format_datetime_readable(row.get("timestamp", ""))
            history_lines.append(f"{timestamp} | {self._history_entry_text(row)}")
        if not history_lines:
            messagebox.showinfo("View History", "No project history is available to view.")
            return
        try:
            content = "\n".join(history_lines)
            destination = Path(tempfile.gettempdir()) / f"{self.selected_project.project_name}_history.txt"
            with destination.open("w", encoding="utf-8") as text_file:
                text_file.write(content)
            if sys.platform.startswith("win"):
                os.startfile(destination)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(destination)])
            else:
                subprocess.run(["xdg-open", str(destination)])
        except Exception as exc:
            messagebox.showerror("View History", f"Unable to open history text file: {exc}")

    def edit_project_details(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        proj = self.selected_project

        form = tk.Toplevel(self.root)
        form.title("Edit Project Details")
        form.transient(self.root)
        form.grab_set()
        form.geometry("520x280")

        ttk.Label(form, text="Project Name:").pack(anchor="w", padx=12, pady=(12, 4))
        name_entry = ttk.Entry(form)
        name_entry.insert(0, proj.project_name)
        name_entry.pack(fill="x", padx=12)

        ttk.Label(form, text="Short Description:").pack(anchor="w", padx=12, pady=(10, 4))
        description_entry = ttk.Entry(form)
        description_entry.insert(0, proj.description)
        description_entry.pack(fill="x", padx=12)

        ttk.Label(form, text="Comma-separated Tags:").pack(anchor="w", padx=12, pady=(10, 4))
        tags_entry = ttk.Entry(form)
        tags_entry.insert(0, proj.tags)
        tags_entry.pack(fill="x", padx=12)

        button_frame = ttk.Frame(form)
        button_frame.pack(fill="x", padx=12, pady=(14, 12))

        def save_details() -> None:
            new_name = name_entry.get().strip() or proj.project_name
            new_description = description_entry.get().strip()
            new_tags = tags_entry.get().strip()
            name_changed = new_name != proj.project_name

            # Rename folder on disk if name changed
            old_folder = Path(proj.root_path)
            new_folder = old_folder.parent / new_name
            if name_changed:
                if new_folder.exists():
                    messagebox.showwarning("Name conflict", f"A folder named '{new_name}' already exists.", parent=form)
                    return
                try:
                    old_folder.rename(new_folder)
                except Exception as exc:
                    messagebox.showerror("Rename failed", f"Could not rename folder: {exc}", parent=form)
                    return

            timestamp = datetime.now().isoformat()
            if name_changed:
                self.csv.append_row("change_log", ChangeRecord(
                    timestamp=timestamp, project_id=proj.project_id, file_id="",
                    change_type="RENAME", old_value=proj.project_name, new_value=new_name,
                    note="Project renamed.",
                ).to_dict())
            if new_description != proj.description:
                self.csv.append_row("change_log", ChangeRecord(
                    timestamp=timestamp, project_id=proj.project_id, file_id="",
                    change_type="EDIT", old_value=proj.description, new_value=new_description,
                    note="Project description updated.",
                ).to_dict())
            if new_tags != proj.tags:
                self.csv.append_row("change_log", ChangeRecord(
                    timestamp=timestamp, project_id=proj.project_id, file_id="",
                    change_type="EDIT", old_value=proj.tags, new_value=new_tags,
                    note="Project tags updated.",
                ).to_dict())

            project_rows = self.csv.read_rows("projects")
            for row in project_rows:
                if row.get("project_id") == proj.project_id:
                    row["project_name"] = new_name
                    row["description"] = new_description
                    row["tags"] = new_tags
                    row["root_path"] = str(new_folder) if name_changed else proj.root_path
                    break
            self.csv.write_rows("projects", project_rows)

            proj.project_name = new_name
            proj.description = new_description
            proj.tags = new_tags
            if name_changed:
                proj.root_path = str(new_folder)

            self.refresh_projects()
            self.project_tree.selection_set(proj.project_id)
            self.on_project_select(None)
            form.destroy()

        ttk.Button(button_frame, text="Save", command=save_details).pack(side="right")
        ttk.Button(button_frame, text="Cancel", command=form.destroy).pack(side="right", padx=(0, 8))
        form.wait_window()

    def view_project_details(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        details = (
            f"Project Name: {self.selected_project.project_name}\n"
            f"Folder: {self.selected_project.root_path}\n"
            f"Description: {self.selected_project.description or 'None'}\n"
            f"Tags: {self.selected_project.tags or 'None'}\n"
            f"Created: {self.selected_project.created_date}"
        )
        messagebox.showinfo("Project Details", details)

    def open_file(self) -> None:
        if not self.selected_project or not self.selected_file:
            return
        file_path = Path(self.selected_project.root_path) / Path(self.selected_file.relative_path)
        if not file_path.exists():
            messagebox.showerror("File missing", "The selected file does not exist on disk.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(file_path)])
            else:
                subprocess.run(["xdg-open", str(file_path)])
        except Exception as exc:
            messagebox.showerror("Open failed", f"Could not open file: {exc}")

    def rename_file(self) -> None:
        if not self.selected_project or not self.selected_file:
            return
        current_path = Path(self.selected_project.root_path) / Path(self.selected_file.relative_path)
        if not current_path.exists():
            messagebox.showerror("File missing", "The selected file does not exist on disk.")
            return
        new_name = simpledialog.askstring("Rename file", "Enter new file name:", initialvalue=current_path.name, parent=self.root)
        if not new_name or new_name == current_path.name:
            return
        new_path = current_path.with_name(new_name)
        if new_path.exists():
            messagebox.showerror("Rename failed", "A file with that name already exists.")
            return
        try:
            current_path.rename(new_path)
        except Exception as exc:
            messagebox.showerror("Rename failed", f"Could not rename file: {exc}")
            return
        new_relative = str(new_path.relative_to(Path(self.selected_project.root_path))).replace("\\", "/")
        file_rows = self.csv.read_rows("files")
        for row in file_rows:
            if row.get("file_id") == self.selected_file.file_id:
                row["relative_path"] = new_relative
                row["extension"] = new_path.suffix.lower()
                row["file_size"] = str(new_path.stat().st_size)
                row["last_modified"] = datetime.fromtimestamp(new_path.stat().st_mtime).isoformat()
                row["checksum"] = compute_checksum(new_path)
                break
        self.csv.write_rows("files", file_rows)
        change = ChangeRecord(
            timestamp=datetime.now().isoformat(),
            project_id=self.selected_project.project_id,
            file_id=self.selected_file.file_id,
            change_type="MOVE",
            old_value=self.selected_file.relative_path,
            new_value=new_relative,
            note="Renamed file inside application.",
        )
        self.csv.append_row("change_log", change.to_dict())
        self.undo_stack.append({
            "type": "rename",
            "project_id": self.selected_project.project_id,
            "source": str(current_path),
            "target": str(new_path),
        })
        self.refresh_files()
        self._show_history()

    def remove_item(self) -> None:
        if not self.selected_project:
            return
        selection = self.file_tree.selection()
        if not selection:
            return
        if not messagebox.askyesno("Remove items", f"Remove {len(selection)} selected item(s) from disk and tracking?"):
            return

        project_root = Path(self.selected_project.root_path)
        file_rows = self.csv.read_rows("files")
        delete_rel_paths: set[str] = set()
        folder_rel_paths: list[str] = []
        recycle_moves: List[dict[str, str]] = []
        removed_rows: List[dict] = []

        for selected_id in selection:
            if selected_id.startswith("file::"):
                delete_rel_paths.add(selected_id.split("::", 1)[1])
            elif selected_id.startswith("folder::"):
                folder_rel_paths.append(selected_id.split("::", 1)[1])

        for folder_rel in folder_rel_paths:
            folder_prefix = f"{folder_rel}/"
            for row in file_rows:
                rel = row.get("relative_path", "")
                if rel == folder_rel or rel.startswith(folder_prefix):
                    delete_rel_paths.add(rel)
            folder_path = project_root / Path(folder_rel)
            if folder_path.exists() and folder_path.is_dir():
                try:
                    recycle_path = self._move_to_recycle(
                        folder_path,
                        original_path=folder_path,
                        project_id=self.selected_project.project_id,
                    )
                    recycle_moves.append({"recycle": str(recycle_path), "original": str(folder_path)})
                except Exception as exc:
                    messagebox.showerror("Remove failed", f"Could not remove folder {folder_path}: {exc}")
                    return

        updated_rows = []
        for row in file_rows:
            rel_path = row.get("relative_path", "")
            if rel_path in delete_rel_paths:
                removed_rows.append(dict(row))
                file_path = project_root / Path(rel_path)
                if file_path.exists():
                    try:
                        recycle_path = self._move_to_recycle(
                            file_path,
                            original_path=file_path,
                            project_id=self.selected_project.project_id,
                        )
                        recycle_moves.append({"recycle": str(recycle_path), "original": str(file_path)})
                    except Exception as exc:
                        messagebox.showerror("Remove failed", f"Could not remove file {file_path}: {exc}")
                        return
                change = ChangeRecord(
                    timestamp=datetime.now().isoformat(),
                    project_id=self.selected_project.project_id,
                    file_id=row.get("file_id", ""),
                    change_type="REMOVE",
                    old_value=rel_path,
                    new_value="",
                    note="Removed item from project and tracking.",
                )
                self.csv.append_row("change_log", change.to_dict())
            else:
                updated_rows.append(row)
        self.csv.write_rows("files", updated_rows)
        inventory_rows = self.csv.read_rows("item_inventory")
        self.csv.write_rows(
            "item_inventory",
            [
                row
                for row in inventory_rows
                if not (
                    row.get("project_id") == self.selected_project.project_id
                    and row.get("relative_path", "") in delete_rel_paths
                )
            ],
        )
        self.selected_file = None
        self.selected_item_kind = ""
        self.selected_item_rel = ""
        if recycle_moves or removed_rows:
            self.undo_stack.append({
                "type": "remove",
                "project_id": self.selected_project.project_id,
                "moves": recycle_moves,
                "rows": removed_rows,
            })
        self.refresh_files()

    def undo_last_operation(self) -> None:
        if not self.undo_stack:
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        entry = self.undo_stack.pop()
        entry_type = str(entry.get("type", ""))

        try:
            if entry_type == "paste":
                for item in reversed(list(entry.get("items", []))):
                    operation = str(item.get("operation", ""))
                    kind = str(item.get("kind", "file"))
                    target = Path(str(item.get("target", "")))
                    if operation == "copy":
                        if target.exists():
                            if kind == "folder" and target.is_dir():
                                shutil.rmtree(target)
                            elif target.is_file():
                                target.unlink()
                    elif operation == "move":
                        source = Path(str(item.get("source", "")))
                        if target.exists() and not source.exists():
                            source.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(target), str(source))

            elif entry_type == "rename":
                source = Path(str(entry.get("source", "")))
                target = Path(str(entry.get("target", "")))
                if target.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    target.rename(source)

            elif entry_type == "remove":
                for move in reversed(list(entry.get("moves", []))):
                    recycle_path = Path(str(move.get("recycle", "")))
                    original_path = Path(str(move.get("original", "")))
                    if recycle_path.exists() and not original_path.exists():
                        original_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(recycle_path), str(original_path))

                rows = list(entry.get("rows", []))
                if rows:
                    file_rows = self.csv.read_rows("files")
                    existing_pairs = {(row.get("project_id", ""), row.get("relative_path", "")) for row in file_rows}
                    for row in rows:
                        key = (row.get("project_id", ""), row.get("relative_path", ""))
                        if key not in existing_pairs:
                            file_rows.append(row)
                            existing_pairs.add(key)
                    self.csv.write_rows("files", file_rows)

            self.refresh_repository()
            messagebox.showinfo("Undo", "Last operation has been undone.")
        except Exception as exc:
            messagebox.showerror("Undo failed", f"Could not undo the last operation: {exc}")

    def delete_project_folder(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return

        confirm_dialog = tk.Toplevel(self.root)
        confirm_dialog.title("Delete Project Folder")
        confirm_dialog.transient(self.root)
        confirm_dialog.grab_set()
        confirm_dialog.geometry("460x190")
        confirm_dialog.resizable(False, False)

        ttk.Label(
            confirm_dialog,
            text=(
                f"This will delete project '{self.selected_project.project_name}', remove all tracked files,\n"
                "and remove the project folder from disk.\n\n"
                "Type  DELETE PROJECT FOLDER  to confirm:"
            ),
            justify="center",
        ).pack(pady=(16, 8))
        confirm_entry = ttk.Entry(confirm_dialog, width=36)
        confirm_entry.pack()
        confirm_entry.focus_set()

        button_frame = ttk.Frame(confirm_dialog)
        button_frame.pack(pady=(12, 0))

        confirmed = {"ok": False}

        def do_confirm() -> None:
            if confirm_entry.get().strip() != "DELETE PROJECT FOLDER":
                messagebox.showwarning("Incorrect", "You must type exactly: DELETE PROJECT FOLDER", parent=confirm_dialog)
                return
            confirmed["ok"] = True
            confirm_dialog.destroy()

        ttk.Button(button_frame, text="Delete", command=do_confirm).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=confirm_dialog.destroy).pack(side="left")
        confirm_dialog.wait_window()

        if not confirmed["ok"]:
            return

        project_root = Path(self.selected_project.root_path)
        project_id = self.selected_project.project_id
        try:
            backup_dir = self._create_auto_backup("delete_project", [project_root])
        except Exception as exc:
            messagebox.showerror("Auto Backup", f"Could not create backup before deleting project: {exc}")
            return
        file_rows = self.csv.read_rows("files")
        project_files = [row for row in file_rows if row.get("project_id") == project_id]
        progress_total = max(1, len(project_files) + 3)
        progress_step = 0

        try:
            self._set_busy(True, f"Deleting project {self.selected_project.project_name}...")
            self._set_busy_progress(0, maximum=progress_total, message=f"Deleting project {self.selected_project.project_name}...")

            for row in project_files:
                change = ChangeRecord(
                    timestamp=datetime.now().isoformat(),
                    project_id=project_id,
                    file_id=row.get("file_id", ""),
                    change_type="REMOVE",
                    old_value=row.get("relative_path", ""),
                    new_value="",
                    note="Project deleted and tracked file removed.",
                )
                self.csv.append_row("change_log", change.to_dict())
                progress_step += 1
                self._set_busy_progress(progress_step, message=f"Removing {Path(row.get('relative_path', '')).name or self.selected_project.project_name}...")

            remaining_files = [row for row in file_rows if row.get("project_id") != project_id]
            self.csv.write_rows("files", remaining_files)
            progress_step += 1
            self._set_busy_progress(progress_step, message="Updating tracked files...")

            inventory_rows = self.csv.read_rows("item_inventory")
            self.csv.write_rows("item_inventory", [row for row in inventory_rows if row.get("project_id") != project_id])
            project_rows = self.csv.read_rows("projects")
            remaining_projects = [row for row in project_rows if row.get("project_id") != project_id]
            self.csv.write_rows("projects", remaining_projects)
            progress_step += 1
            self._set_busy_progress(progress_step, message="Updating project list...")

            if project_root.exists() and project_root.is_dir():
                try:
                    self._move_to_recycle(project_root, original_path=project_root, project_id=project_id)
                except Exception as exc:
                    messagebox.showwarning("Delete folder", f"Could not delete folder on disk: {exc}")
            progress_step += 1
            self._set_busy_progress(progress_step, message="Refreshing views...")

            self.selected_project = None
            self.selected_file = None
            self.refresh_projects()
            self.refresh_files()
        finally:
            self._set_busy(False)
        messagebox.showinfo("Delete complete", f"Project deleted. Auto backup saved to:\n{backup_dir}")

    def _auto_sync_repository(self) -> None:
        """On startup: remove projects whose folder is gone and register any new
        subfolders found inside the repository directory."""
        repo = self.repository_folder
        repo.mkdir(parents=True, exist_ok=True)
        project_rows = self.csv.read_rows("projects")

        # Separate valid from stale projects
        valid_rows: List[dict] = []
        removed_ids: set = set()
        for row in project_rows:
            root_path = Path(row.get("root_path", ""))
            if root_path.exists() and root_path.is_dir():
                valid_rows.append(row)
            else:
                removed_ids.add(row.get("project_id", ""))

        if removed_ids:
            self.csv.write_rows("projects", valid_rows)
            file_rows = self.csv.read_rows("files")
            self.csv.write_rows("files", [r for r in file_rows if r.get("project_id") not in removed_ids])
            todo_rows = self.csv.read_rows("todos")
            self.csv.write_rows("todos", [r for r in todo_rows if r.get("project_id") not in removed_ids])
            inventory_rows = self.csv.read_rows("item_inventory")
            self.csv.write_rows("item_inventory", [r for r in inventory_rows if r.get("project_id") not in removed_ids])

        # Register new subfolders in the repository that are not yet tracked
        tracked_paths = {Path(row.get("root_path", "")).resolve() for row in valid_rows}
        for subfolder in sorted(repo.iterdir()):
            if not subfolder.is_dir():
                continue
            if subfolder.name == SHARED_REPO_SETTINGS_DIR:
                continue
            if subfolder.resolve() in tracked_paths:
                continue
            project_id = self.csv.next_id("projects", "project_id")
            project = Project(
                project_id=project_id,
                project_name=subfolder.name,
                root_path=str(subfolder),
                description="",
                tags="",
                pinned="0",
                created_date=datetime.now().isoformat(),
                last_scanned_date="",
            )
            self.csv.append_row("projects", project.to_dict())

    def refresh_repository(self) -> None:
        """Refresh all repository projects and tracked file metadata globally."""
        try:
            selected_project_id = self.selected_project.project_id if self.selected_project else None

            self._auto_sync_repository()
            project_rows = self.csv.read_rows("projects")
            all_file_rows = self.csv.read_rows("files")
            updated_all_rows: List[dict] = []
            active_projects = [
                row for row in project_rows
                if Path(row.get("root_path", "")).exists() and Path(row.get("root_path", "")).is_dir()
            ]

            self._set_busy(True, "Refreshing repository...")
            self._set_busy_progress(0, maximum=max(1, len(active_projects)), message="Refreshing repository...")

            max_file_id = 0
            for row in all_file_rows:
                try:
                    max_file_id = max(max_file_id, int(row.get("file_id", "0")))
                except ValueError:
                    continue

            for index, project_row in enumerate(active_projects, start=1):
                project_id = project_row.get("project_id", "")
                root_folder = Path(project_row.get("root_path", ""))
                project_name = project_row.get("project_name", "") or root_folder.name
                self._set_busy_progress(index - 1, message=f"Refreshing {project_name}...")

                scanned = list(scan_project_files(root_folder))
                self._update_item_inventory_for_project(project_id, scanned)
                tracked_rows = [row for row in all_file_rows if row.get("project_id") == project_id]
                tracked = [TrackedFile.from_dict(row) for row in tracked_rows]
                changes = detect_changes(project_id, tracked, scanned)
                for record in changes:
                    self.csv.append_row("change_log", record.to_dict())
                    if record.change_type in {"ADD", "MODIFY", "MOVE", "META_UPDATE"}:
                        target_rel = record.new_value or record.old_value
                        if target_rel:
                            target_path = root_folder / Path(target_rel)
                            if target_path.exists() and target_path.is_file():
                                self._save_snapshot_for_file(project_id, target_path, target_rel)

                scan_by_rel = {row["relative_path"]: row for row in scanned}
                scan_by_checksum = {row["checksum"]: row for row in scanned}
                project_updated_rows: List[dict] = []

                for row in tracked_rows:
                    relative = row.get("relative_path", "")
                    checksum = row.get("checksum", "")
                    current = scan_by_rel.get(relative) or scan_by_checksum.get(checksum)
                    if not current:
                        continue
                    row["relative_path"] = current["relative_path"]
                    row["extension"] = current["extension"]
                    row["file_size"] = current["file_size"]
                    row["last_modified"] = current["last_modified"]
                    row["checksum"] = current["checksum"]
                    project_updated_rows.append(row)

                existing_paths = {row.get("relative_path", "") for row in project_updated_rows}
                for row in scanned:
                    rel_path = row["relative_path"]
                    if rel_path in existing_paths:
                        continue
                    max_file_id += 1
                    project_updated_rows.append({
                        "file_id": str(max_file_id),
                        "project_id": project_id,
                        "relative_path": rel_path,
                        "extension": row["extension"],
                        "file_size": row["file_size"],
                        "last_modified": row["last_modified"],
                        "checksum": row["checksum"],
                        "notes": "",
                    })

                project_row["last_scanned_date"] = datetime.now().isoformat()
                updated_all_rows.extend(project_updated_rows)
                self._set_busy_progress(index, message=f"Refreshing {project_name}...")

            self.csv.write_rows("files", updated_all_rows)
            self.csv.write_rows("projects", project_rows)

            self.refresh_projects()
            if selected_project_id and any(row.get("project_id") == selected_project_id for row in project_rows):
                self.project_tree.selection_set(selected_project_id)
                self.on_project_select(None)
            else:
                self.selected_project = None
                self.current_folder_rel = ""
                self.refresh_files()
            self._update_dashboard()
        finally:
            self._set_busy(False)

    def _update_item_inventory_for_project(self, project_id: str, scanned_rows: List[dict[str, str]]) -> None:
        now = datetime.now().isoformat()
        all_inventory = self.csv.read_rows("item_inventory")
        project_inventory = [row for row in all_inventory if row.get("project_id") == project_id]
        other_inventory = [row for row in all_inventory if row.get("project_id") != project_id]

        current_by_rel = {row["relative_path"]: row for row in scanned_rows}
        current_checksums = {row["checksum"] for row in scanned_rows}

        # Detect manual removals based on prior inventory snapshots.
        for row in project_inventory:
            prev_rel = row.get("relative_path", "")
            prev_checksum = row.get("checksum", "")
            if prev_rel not in current_by_rel and prev_checksum not in current_checksums:
                self.csv.append_row(
                    "change_log",
                    ChangeRecord(
                        timestamp=now,
                        project_id=project_id,
                        file_id=prev_checksum,
                        change_type="MANUAL_REMOVE",
                        old_value=prev_rel,
                        new_value="",
                        note=f"Manual removal detected: {prev_rel} ({prev_checksum})",
                    ).to_dict(),
                )

        rebuilt_project_inventory: List[dict[str, str]] = []
        for row in scanned_rows:
            rebuilt_project_inventory.append(
                {
                    "project_id": project_id,
                    "item_id": row["checksum"],
                    "relative_path": row["relative_path"],
                    "extension": row["extension"],
                    "checksum": row["checksum"],
                    "last_seen": now,
                }
            )

        self.csv.write_rows("item_inventory", other_inventory + rebuilt_project_inventory)

    def _create_auto_backup(self, reason: str, project_roots: Optional[List[Path]] = None) -> Path:
        if not self.backup_folder:
            raise RuntimeError("Backup folder is not configured.")

        backup_root = self.backup_folder.resolve() / SHARED_REPO_SETTINGS_DIR / BACKUPS_SUBDIR
        backup_root.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = backup_root / f"auto_backup_{stamp}_{reason}"
        counter = 1
        while destination.exists():
            destination = backup_root / f"auto_backup_{stamp}_{reason}_{counter}"
            counter += 1
        destination.mkdir(parents=True, exist_ok=True)

        # Build copy task list first so progress can be deterministic.
        copy_tasks: List[tuple[Path, Path]] = []
        data_dest = destination / "Data"
        data_dest.mkdir(parents=True, exist_ok=True)
        for name in ("projects.csv", "files.csv", "change_log.csv", "todos.csv", "item_inventory.csv"):
            src = self.csv.base_dir / name
            if src.exists() and src.is_file():
                copy_tasks.append((src, data_dest / name))

        projects_dest = destination / "Projects"
        projects_dest.mkdir(parents=True, exist_ok=True)
        roots = project_roots if project_roots is not None else [Path(row.get("root_path", "")) for row in self.csv.read_rows("projects")]
        for root in roots:
            try:
                resolved = root.resolve()
            except Exception:
                continue
            if not resolved.exists() or not resolved.is_dir():
                continue
            project_target_root = projects_dest / resolved.name
            project_target_root.mkdir(parents=True, exist_ok=True)
            for child in resolved.rglob("*"):
                relative = child.relative_to(resolved)
                target = project_target_root / relative
                if child.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif child.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    copy_tasks.append((child, target))

        progress_dialog = tk.Toplevel(self.root)
        progress_dialog.title("Auto Backup In Progress")
        progress_dialog.transient(self.root)
        progress_dialog.grab_set()
        progress_dialog.geometry("520x150")
        progress_dialog.resizable(False, False)

        status_var = tk.StringVar(value="Preparing backup...")
        ttk.Label(progress_dialog, textvariable=status_var, wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(12, 6))
        progress = ttk.Progressbar(progress_dialog, mode="determinate", maximum=max(1, len(copy_tasks)))
        progress.pack(fill="x", padx=12, pady=(0, 8))
        count_var = tk.StringVar(value=f"0 / {len(copy_tasks)} files")
        ttk.Label(progress_dialog, textvariable=count_var).pack(anchor="w", padx=12)

        cancelled = {"value": False}

        def cancel_backup() -> None:
            cancelled["value"] = True

        progress_dialog.protocol("WM_DELETE_WINDOW", cancel_backup)
        ttk.Button(progress_dialog, text="Cancel", command=cancel_backup).pack(anchor="e", padx=12, pady=(8, 8))

        try:
            for index, (src, dst) in enumerate(copy_tasks, start=1):
                if cancelled["value"]:
                    raise RuntimeError("Backup operation was cancelled by user.")

                status_var.set(f"Copying: {src.name}")
                shutil.copy2(src, dst)

                # Integrity verification: always compare size; checksum for smaller files.
                src_stat = src.stat()
                dst_stat = dst.stat()
                if src_stat.st_size != dst_stat.st_size:
                    raise RuntimeError(f"Copied file size mismatch for '{src}'.")
                if src_stat.st_size <= 50 * 1024 * 1024:
                    if compute_checksum(src) != compute_checksum(dst):
                        raise RuntimeError(f"Checksum verification failed for '{src}'.")

                progress["value"] = index
                count_var.set(f"{index} / {len(copy_tasks)} files")
                progress_dialog.update_idletasks()
                self.root.update()
        except Exception:
            try:
                if destination.exists():
                    shutil.rmtree(destination)
            finally:
                progress_dialog.destroy()
            raise

        progress_dialog.destroy()
        return destination

    def export_backup(self) -> None:
        session_root = self._session_archive_root()
        initial_file = f"session_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        destination = filedialog.asksaveasfilename(
            title="Capture Session (ZIP)",
            initialdir=str(session_root) if session_root else str(self.app_base_dir),
            initialfile=initial_file,
            defaultextension=".zip",
            filetypes=[("ZIP files", "*.zip")],
        )
        if not destination:
            return
        try:
            self._set_busy(True, "Capturing session archive...")
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                for name in ("projects.csv", "files.csv", "change_log.csv", "todos.csv", "item_inventory.csv"):
                    path = self.csv.base_dir / name
                    if path.exists():
                        archive.write(path, arcname=name)
                for folder_name in ("repository", "snapshots", "recycle_bin"):
                    folder = self.app_base_dir / folder_name
                    if folder.exists():
                        for child in folder.rglob("*"):
                            if child.is_file():
                                archive.write(child, arcname=str(child.relative_to(self.app_base_dir)).replace("\\", "/"))
            messagebox.showinfo("Capture Session", "Session archive captured successfully.")
        except Exception as exc:
            messagebox.showerror("Capture Session", f"Session capture failed: {exc}")
        finally:
            self._set_busy(False)

    def import_backup(self) -> None:
        session_root = self._session_archive_root()
        source = filedialog.askopenfilename(
            title="Restore Session (ZIP)",
            initialdir=str(session_root) if session_root else str(self.app_base_dir),
            filetypes=[("ZIP files", "*.zip")],
        )
        if not source:
            return
        if not messagebox.askyesno("Restore Session", "Restoring a session archive will overwrite current local data. Continue?"):
            return
        base = self.app_base_dir
        try:
            self._set_busy(True, "Restoring session archive...")
            with zipfile.ZipFile(source, "r") as archive:
                archive.extractall(base)
            self._auto_sync_repository()
            self.refresh_projects()
            self.refresh_files()
            self._show_history()
            messagebox.showinfo("Restore Session", "Session archive restored successfully.")
        except Exception as exc:
            messagebox.showerror("Restore Session", f"Session restore failed: {exc}")
        finally:
            self._set_busy(False)

    def restore_project_from_backup(self) -> None:
        if not self.backup_folder:
            messagebox.showwarning("Restore Project", "Backup folder is not configured in Settings.")
            return

        backup_root = self.backup_folder.resolve() / SHARED_REPO_SETTINGS_DIR / BACKUPS_SUBDIR
        if not backup_root.exists() or not backup_root.is_dir():
            messagebox.showinfo(
                "Restore Project",
                "No auto-backup snapshots found.\n\n"
                "Auto-backups are created automatically when:\n"
                "  • You delete a project\n"
                "  • You reset all data\n\n"
                f"Backup folder path:\n{backup_root}"
            )
            return

        selected_path = filedialog.askdirectory(
            title="Select a backup snapshot folder (auto_backup_*)",
            initialdir=str(backup_root),
        )
        if not selected_path:
            return

        backup_folder_path = Path(selected_path).resolve()

        # Verify it's inside the backup root
        try:
            backup_folder_path.relative_to(backup_root)
        except ValueError:
            messagebox.showerror("Restore", "Selected folder must be inside the Backups directory.")
            return

        # Check for Projects subfolder
        projects_dir = backup_folder_path / "Projects"
        if not projects_dir.exists():
            messagebox.showwarning("Restore", f"Selected backup folder has no Projects subfolder:\n{backup_folder_path}")
            return

        projects = [p.name for p in projects_dir.iterdir() if p.is_dir()]
        if not projects:
            messagebox.showinfo("Restore", "No projects found in this backup.")
            return

        # Show project selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Project to Restore")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("400x300")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        ttk.Label(dialog, text=f"Projects in backup:\n{backup_folder_path.name}", font=("TkDefaultFont", 9)).pack(anchor="w", padx=12, pady=(12, 8))

        listbox = tk.Listbox(dialog, height=10)
        listbox.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        for project in sorted(projects):
            listbox.insert("end", project)

        selected_project = {}

        def do_restore() -> None:
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning("Restore", "Please select a project.", parent=dialog)
                return
            selected_project["name"] = listbox.get(selection[0])
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.pack(side="bottom", fill="x", padx=12, pady=(0, 12))

        ttk.Button(btn_row, text="Restore", command=do_restore).pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))

        dialog.wait_window()

        if not selected_project:
            return

        project_name = selected_project["name"]
        source_project = projects_dir / project_name
        target_project = self.repository_folder / project_name

        if target_project.exists():
            overwrite = messagebox.askyesno(
                "Restore Project",
                f"Project '{project_name}' already exists in repository. Overwrite it?",
            )
            if not overwrite:
                return

        try:
            self._set_busy(True, f"Restoring {project_name}...")
            if target_project.exists() and target_project.is_dir():
                shutil.rmtree(target_project)
            shutil.copytree(source_project, target_project)
            self.refresh_repository()

            # Select restored project if it exists in current project list.
            restored = next((p for p in self.projects if p.project_name == project_name), None)
            if restored:
                self.project_tree.selection_set(restored.project_id)
                self.on_project_select(None)
        except Exception as exc:
            messagebox.showerror("Restore Project", f"Could not restore project from backup: {exc}")
            return
        finally:
            self._set_busy(False)

        messagebox.showinfo("Restore Project", f"Project '{project_name}' restored successfully from backup.")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-f>", lambda event: self._focus_file_search())
        self.root.bind("<Control-n>", lambda event: self.add_project())
        self.root.bind("<Control-c>", self._shortcut_copy)
        self.root.bind("<Control-x>", self._shortcut_cut)
        self.root.bind("<Control-v>", self._shortcut_paste)
        self.root.bind("<Control-z>", self._shortcut_undo)
        self.root.bind("<BackSpace>", self._shortcut_back)
        self.root.bind("<Delete>", self._shortcut_delete)
        self.root.bind("<Escape>", self._shortcut_clear_selection)
        self.root.bind("<Control-a>", self._shortcut_select_all)
        self.root.bind("<F5>", lambda event: self.refresh_repository())

    def _focused_widget_is_text_input(self) -> bool:
        focused = self.root.focus_get()
        return isinstance(focused, (tk.Entry, ttk.Entry, tk.Text))

    def _shortcut_copy(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        self.copy_selected_items()
        return "break"

    def _shortcut_cut(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        self.move_selected_items()
        return "break"

    def _shortcut_paste(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        self.paste_pending_items_here()
        return "break"

    def _shortcut_undo(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        self.undo_last_operation()
        return "break"

    def _shortcut_back(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        self.go_back_folder()
        return "break"

    def _shortcut_delete(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        if self.root.focus_get() == self.todo_listbox and self.todo_listbox.curselection():
            self.remove_todo_item()
            return "break"
        self.remove_item()
        return "break"

    def _shortcut_select_all(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        focused = self.root.focus_get()
        if focused == self.todo_listbox:
            self.todo_listbox.selection_set(0, tk.END)
            return "break"
        if focused == self.file_tree:
            all_ids = self.file_tree.get_children()
            if all_ids:
                self.file_tree.selection_set(all_ids)
            return "break"
        return None

    def _shortcut_clear_selection(self, event: tk.Event) -> str | None:
        if self._focused_widget_is_text_input():
            return None
        focused = self.root.focus_get()
        if focused == self.project_tree:
            self.project_tree.selection_remove(self.project_tree.selection())
            self.on_project_select(None)
            self.refresh_files()
            self._show_history()
            return "break"
        if focused == self.file_tree:
            self.file_tree.selection_remove(self.file_tree.selection())
            self.on_file_select(None)
            return "break"
        if focused == self.todo_listbox:
            self.todo_listbox.selection_clear(0, tk.END)
            return "break"
        return None

    def _focus_file_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, tk.END)

    def _on_window_resize(self, event: object) -> None:
        """Comprehensive dynamic scaling for all UI elements on window resize."""
        current_width = self.root.winfo_width()
        current_height = self.root.winfo_height()
        if current_width <= 1 or current_height <= 1:
            return

        # Calculate scale factor (0.6 to 1.0)
        old_scale = self.scale_factor
        self.scale_factor = max(0.6, min(1.0, current_width / self.base_window_width))
        
        if abs(self.scale_factor - old_scale) < 0.01:
            return  # Skip if change is minimal

        # Scale font sizes
        scaled_font_size = int(max(8, 9 * self.scale_factor))

        self._fit_project_tree_columns()
        self._fit_file_tree_columns()

        # Scale text widget dimensions and fonts
        new_details_height = max(4, int(self.details_text_base_height * self.scale_factor))
        new_history_height = max(4, int(self.history_text_base_height * self.scale_factor))
        new_todo_height = max(4, int(self.todo_listbox_base_height * self.scale_factor))

        self.details_text.config(height=new_details_height, font=("TkDefaultFont", scaled_font_size))
        self.history_text.config(height=new_history_height, font=("TkDefaultFont", scaled_font_size))
        self.todo_listbox.config(height=new_todo_height, font=("TkDefaultFont", scaled_font_size))

        # Scale dashboard canvas heights
        self._apply_dashboard_compact_layout()

        # Redraw dashboard with new dimensions
        self._update_dashboard()

    def _fit_project_tree_columns(self) -> None:
        tree_width = self.project_tree.winfo_width()
        if tree_width <= 1:
            return

        usable_width = max(120, tree_width - 6)
        name_width = int(usable_width * self.project_tree_name_ratio)
        tags_width = max(50, usable_width - name_width)
        name_width = max(70, usable_width - tags_width)

        self.project_tree.column("name", width=name_width, anchor="w", stretch=False)
        self.project_tree.column("tags", width=tags_width, anchor="w", stretch=False)

    def _reset_project_tree_columns_to_default(self) -> None:
        self._fit_project_tree_columns()

    def _reset_file_tree_columns_to_default(self) -> None:
        self._fit_file_tree_columns()

    def _fit_file_tree_columns(self) -> None:
        tree_width = self.file_tree.winfo_width()
        if tree_width <= 1:
            return

        usable_width = max(180, tree_width - 6)
        if usable_width < 260:
            size_width = max(50, int(usable_width * 0.18))
            modified_width = max(70, int(usable_width * 0.24))
            name_width = max(60, usable_width - size_width - modified_width)
        else:
            name_width = int(usable_width * self.file_tree_name_ratio)
            size_width = int(usable_width * self.file_tree_size_ratio)
            modified_width = usable_width - name_width - size_width

            size_width = max(70, size_width)
            modified_width = max(120, modified_width)
            name_width = max(90, usable_width - size_width - modified_width)

        self.file_tree.column("#0", width=name_width, anchor="w", stretch=False)
        self.file_tree.column("size", width=size_width, anchor="w", stretch=False)
        self.file_tree.column("modified", width=modified_width, anchor="w", stretch=False)

    def _apply_dashboard_compact_layout(self) -> None:
        frame_width = self.dashboard_frame.winfo_width()
        if frame_width <= 1:
            frame_width = 200
        width_scale = max(0.55, min(1.0, frame_width / 240))
        scaled_activity_height = max(22, int(38 * self.scale_factor * width_scale))
        scaled_top_height = max(26, int(44 * self.scale_factor * width_scale))
        self.dash_activity_canvas.config(height=scaled_activity_height)
        self.dash_top_canvas.config(height=scaled_top_height)
        self.dashboard_active_project.config(wraplength=max(90, frame_width - 24))

    def _reset_main_pane_sashes_to_default(self) -> None:
        total = self.main_pane.winfo_width()
        if total <= 1:
            return
        side = total // 6
        self.main_pane.sashpos(0, side)
        self.main_pane.sashpos(1, total - side)

    def _on_main_pane_double_click(self, event: tk.Event) -> str | None:
        sash_hit_padding = 8
        if abs(event.x - self.main_pane.sashpos(0)) <= sash_hit_padding or abs(event.x - self.main_pane.sashpos(1)) <= sash_hit_padding:
            self._reset_main_pane_sashes_to_default()
            return "break"
        return None

    def _autofit_treeview_column(self, tree: ttk.Treeview, column_id: str, min_width: int = 60) -> None:
        if not column_id:
            return

        columns = list(tree["columns"])
        column_key = column_id
        if column_id.startswith("#") and column_id != "#0":
            try:
                index = int(column_id[1:]) - 1
            except ValueError:
                return
            if index < 0 or index >= len(columns):
                return
            column_key = columns[index]

        heading_text = str(tree.heading(column_key, "text") or "")
        max_chars = len(heading_text)
        for item_id in tree.get_children(""):
            if column_key == "#0":
                value = str(tree.item(item_id, "text") or "")
            else:
                value = str(tree.set(item_id, column_key) or "")
            max_chars = max(max_chars, len(value))

        width = max(min_width, (max_chars * 8) + 24)
        tree.column(column_key, width=width, stretch=False)

    def _move_to_recycle(self, path: Path, original_path: Optional[Path] = None, project_id: str = "") -> Path:
        self.recycle_bin_folder.mkdir(parents=True, exist_ok=True)
        source = path.resolve()
        original = (original_path or path).resolve()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        is_directory = source.is_dir()

        rel_parent = Path("misc")
        project_folder_name = "misc"
        relative_path = original.name
        if project_id:
            project = self.selected_project if self.selected_project and self.selected_project.project_id == project_id else self._find_project_by_id(project_id)
            if project is not None:
                project_root = Path(project.root_path).resolve()
                project_folder_name = project_root.name
                try:
                    relative = original.relative_to(project_root)
                    relative_path = "" if str(relative) == "." else str(relative).replace("\\", "/")
                    rel_parent = Path(project_folder_name) / (relative.parent if str(relative) != "." else Path())
                except Exception:
                    rel_parent = Path(project_folder_name)
                    relative_path = original.name
            else:
                project_folder_name = project_id
                rel_parent = Path(project_folder_name)

        recycle_dir = self.recycle_bin_folder / rel_parent
        recycle_dir.mkdir(parents=True, exist_ok=True)
        destination = recycle_dir / f"{stamp}_{original.name}"
        shutil.move(str(source), str(destination))

        manifest = self._load_recycle_manifest()
        manifest.append(
            {
                "recycle_path": str(destination),
                "original_path": str(original),
                "project_id": project_id,
                "project_folder_name": project_folder_name,
                "relative_path": relative_path,
                "item_type": "folder" if is_directory else "file",
                "deleted_at": datetime.now().isoformat(),
            }
        )
        self._save_recycle_manifest(manifest)
        return destination

    def restore_recycle_item(self) -> None:
        if not self.selected_project:
            messagebox.showwarning(
                "Recycle Bin",
                "Select a project first. Restore from recycle bin is limited to the active project to prevent file mixing.",
            )
            return

        project_root = Path(self.selected_project.root_path).resolve()
        project_folder_name = project_root.name
        manifest = self._load_recycle_manifest()
        valid_entries = []
        for row in manifest:
            recycle_path = Path(str(row.get("recycle_path", "")))
            if not recycle_path.exists():
                continue

            row_project_id = str(row.get("project_id", ""))
            row_project_folder = str(row.get("project_folder_name", "")).strip()
            original_path_text = str(row.get("original_path", "")).strip()

            belongs_to_project = row_project_id == self.selected_project.project_id
            if not belongs_to_project and original_path_text:
                try:
                    Path(original_path_text).resolve().relative_to(project_root)
                    belongs_to_project = True
                except Exception:
                    belongs_to_project = False
            if not belongs_to_project and row_project_folder:
                belongs_to_project = row_project_folder == project_folder_name

            if belongs_to_project:
                valid_entries.append(row)

        if not valid_entries:
            messagebox.showinfo(
                "Recycle Bin",
                f"No recyclable items are available for project '{self.selected_project.project_name}'.",
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Restore Recycle Bin Item - {self.selected_project.project_name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("920x420")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        tree = ttk.Treeview(dialog, columns=("type", "deleted", "path"), show="headings", selectmode="extended")
        tree.heading("type", text="Type")
        tree.heading("deleted", text="Deleted Time")
        tree.heading("path", text="Project Path")
        tree.column("type", width=100, anchor="w")
        tree.column("deleted", width=180, anchor="w")
        tree.column("path", width=600, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        scroll = ttk.Scrollbar(dialog, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=10)
        tree.configure(yscrollcommand=scroll.set)

        ttk.Label(
            dialog,
            text=f"Showing recycle bin items only for project folder: {project_root}",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 8))

        index_map: dict[str, dict[str, str]] = {}
        for idx, row in enumerate(valid_entries):
            iid = f"rec::{idx}"
            deleted_display = self._format_datetime_readable(row.get("deleted_at", ""))
            relative_path = str(row.get("relative_path", "")).strip()
            if not relative_path:
                original_path_text = str(row.get("original_path", "")).strip()
                if original_path_text:
                    try:
                        relative_path = str(Path(original_path_text).resolve().relative_to(project_root)).replace("\\", "/")
                    except Exception:
                        relative_path = Path(original_path_text).name
            display_path = relative_path or Path(str(row.get("original_path", ""))).name
            item_type = str(row.get("item_type", "")).strip() or ("folder" if Path(str(row.get("recycle_path", ""))).is_dir() else "file")
            tree.insert("", "end", iid=iid, values=(item_type.title(), deleted_display, display_path))
            index_map[iid] = row

        btn_row = ttk.Frame(dialog)
        btn_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        def do_restore() -> None:
            selected = tree.selection()
            if not selected:
                return

            restored_paths: set[str] = set()
            restored_count = 0
            for iid in selected:
                row = index_map.get(iid)
                if not row:
                    continue
                recycle_path = Path(str(row.get("recycle_path", "")))
                if not recycle_path.exists():
                    continue

                relative_path = str(row.get("relative_path", "")).strip()
                if relative_path:
                    original_path = project_root / Path(relative_path)
                else:
                    original_path_text = str(row.get("original_path", "")).strip()
                    if not original_path_text:
                        continue
                    try:
                        original_path = project_root / Path(Path(original_path_text).resolve().relative_to(project_root))
                    except Exception:
                        messagebox.showwarning(
                            "Restore",
                            f"Skipped an item that does not belong to the active project:\n{original_path_text}",
                            parent=dialog,
                        )
                        continue

                try:
                    original_path.resolve().relative_to(project_root)
                except Exception:
                    messagebox.showwarning(
                        "Restore",
                        f"Skipped an item outside the active project:\n{original_path}",
                        parent=dialog,
                    )
                    continue

                if original_path.exists():
                    messagebox.showwarning("Restore", f"Skip existing path:\n{original_path}", parent=dialog)
                    continue
                original_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(recycle_path), str(original_path))
                restored_paths.add(str(recycle_path))
                restored_count += 1

            if restored_paths:
                self._save_recycle_manifest([row for row in manifest if str(row.get("recycle_path", "")) not in restored_paths])

            dialog.destroy()
            if restored_count:
                messagebox.showinfo("Restore", f"Restored {restored_count} item(s) from recycle bin.")

        ttk.Button(btn_row, text="Restore Selected", command=do_restore).pack(side="right")
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.wait_window()

    def _snapshot_path_for_relative(self, project_id: str, relative_path: str) -> Path:
        safe_rel = Path(relative_path)
        return self.snapshots_folder / project_id / safe_rel

    def _list_snapshots_for_relative(self, project_id: str, relative_path: str) -> List[Path]:
        snapshot_dir = self._snapshot_path_for_relative(project_id, relative_path)
        if not snapshot_dir.exists():
            return []
        return sorted([p for p in snapshot_dir.iterdir() if p.is_file()])

    def _save_snapshot_for_file(self, project_id: str, file_path: Path, relative_path: str) -> None:
        if not file_path.exists() or not file_path.is_file():
            return
        snapshot_dir = self._snapshot_path_for_relative(project_id, relative_path)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        checksum = compute_checksum(file_path)
        existing = sorted([p for p in snapshot_dir.iterdir() if p.is_file()])
        if existing and f"__{checksum}" in existing[-1].name:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        ext = file_path.suffix or ".bin"
        target = snapshot_dir / f"{stamp}__{checksum}{ext}"
        shutil.copy2(file_path, target)

    def _update_dashboard(self) -> None:
        self._apply_dashboard_compact_layout()
        projects = [row for row in self.csv.read_rows("projects") if not self._is_internal_project_row(row)]
        visible_project_ids = {row.get("project_id", "") for row in projects}
        files = [row for row in self.csv.read_rows("files") if row.get("project_id", "") in visible_project_ids]
        changes = [row for row in self.csv.read_rows("change_log") if row.get("project_id", "") in visible_project_ids]
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        today_count = sum(1 for row in changes if row.get("timestamp", "").startswith(today_str))

        activity_counts: dict[str, int] = {}
        for row in changes:
            pid = row.get("project_id", "")
            activity_counts[pid] = activity_counts.get(pid, 0) + 1

        most_active_name = "N/A"
        if activity_counts:
            most_active_id = max(activity_counts, key=activity_counts.get)
            for project in projects:
                if project.get("project_id") == most_active_id:
                    most_active_name = project.get("project_name", "N/A")
                    break

        self.dashboard_total_projects.config(text=str(len(projects)))
        self.dashboard_total_files.config(text=str(len(files)))
        self.dashboard_changes_today.config(text=f"{today_count} today")
        self.dashboard_active_project.config(text=most_active_name)

        self._draw_stat_bar(self.dash_projects_bar, len(projects), 20, "#4c9be8")
        self._draw_stat_bar(self.dash_files_bar, len(files), 500, "#43a047")

        day_counts: list = []
        day_labels: list = []
        for i in range(6, -1, -1):
            day = now - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            day_counts.append(sum(1 for row in changes if row.get("timestamp", "").startswith(day_str)))
            day_labels.append(day.strftime("%a"))
        self._draw_activity_bars(self.dash_activity_canvas, day_counts, day_labels)

        if activity_counts and projects:
            project_name_map = {p.get("project_id"): p.get("project_name", "?") for p in projects}
            top = sorted(activity_counts.items(), key=lambda x: x[1], reverse=True)[:4]
            top_named = [(project_name_map.get(pid, "?"), count) for pid, count in top]
            self._draw_top_projects_bars(self.dash_top_canvas, top_named)
        else:
            self.dash_top_canvas.delete("all")

    def _draw_stat_bar(self, canvas: tk.Canvas, value: int, max_val: int, color: str) -> None:
        canvas.delete("all")
        canvas.update_idletasks()
        w = canvas.winfo_width()
        if w <= 1:
            w = 120
        fill_w = int(min(value / max_val, 1.0) * w) if max_val > 0 else 0
        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, 3, fill=color, outline="")

    def _draw_activity_bars(self, canvas: tk.Canvas, counts: list, labels: list) -> None:
        canvas.delete("all")
        canvas.update_idletasks()
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            w = 160
        if h <= 1:
            h = 38
        n = len(counts)
        if n == 0:
            return
        max_count = max(counts) if max(counts) > 0 else 1
        label_h = 10
        bar_area_h = h - label_h - 2
        gap = 2
        bar_w = max(4, (w - gap * (n + 1)) // n)
        bar_colors = ["#90caf9"] * (n - 1) + ["#1565c0"]
        for i, (count, label) in enumerate(zip(counts, labels)):
            x0 = gap + i * (bar_w + gap)
            x1 = x0 + bar_w
            canvas.create_rectangle(x0, 0, x1, bar_area_h, fill="#eeeeee", outline="")
            if count > 0:
                bar_h = max(2, int(count / max_count * bar_area_h))
                canvas.create_rectangle(x0, bar_area_h - bar_h, x1, bar_area_h, fill=bar_colors[i], outline="")
            canvas.create_text(x0 + bar_w // 2, h - 2, text=label[0], font=("TkDefaultFont", 7), anchor="s", fill="#757575")

    def _draw_top_projects_bars(self, canvas: tk.Canvas, top: list) -> None:
        canvas.delete("all")
        canvas.update_idletasks()
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            w = 160
        if h <= 1:
            h = 44
        if not top:
            return
        max_count = max(count for _, count in top)
        if max_count == 0:
            return
        n = len(top)
        row_h = h // n
        palette = ["#4c9be8", "#43a047", "#ef6c00", "#9c27b0"]
        for i, (name, count) in enumerate(top):
            y0 = i * row_h + 2
            y1 = y0 + row_h - 4
            bar_w = max(2, int(count / max_count * (w - 4)))
            canvas.create_rectangle(2, y0, 2 + bar_w, y1, fill=palette[i % len(palette)], outline="")
            truncated = name[:14] + "\u2026" if len(name) > 14 else name
            canvas.create_text(6, (y0 + y1) // 2, text=truncated, anchor="w", font=("TkDefaultFont", 7), fill="white")
