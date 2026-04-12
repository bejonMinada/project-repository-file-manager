import os
import shutil
import subprocess
import sys
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

APP_VERSION = "1.2"

class DocumentTrackerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Project File Manager")
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
        self.csv = CSVManager()
        self.repository_folder = Path(__file__).resolve().parent / "repository"
        self.repository_folder.mkdir(parents=True, exist_ok=True)
        self.snapshots_folder = Path(__file__).resolve().parent / "snapshots"
        self.snapshots_folder.mkdir(parents=True, exist_ok=True)
        self.recycle_bin_folder = Path(__file__).resolve().parent / "recycle_bin"
        self.recycle_bin_folder.mkdir(parents=True, exist_ok=True)
        self.projects: List[Project] = []
        self.tracked_files: List[TrackedFile] = []
        self.change_rows: List[ChangeRecord] = []
        self.selected_project: Optional[Project] = None
        self.selected_file: Optional[TrackedFile] = None
        self.current_folder_rel: str = ""
        self.selected_item_kind: str = ""
        self.selected_item_rel: str = ""
        self.sort_state = {
            "projects": {"name": False, "tags": False},
            "files": {"path": False, "size": False, "modified": False},
        }
        self.project_todos: dict[str, List[dict]] = {}
        self.scale_factor = 1.0
        self.base_window_width = 1200
        self._build_ui()
        self._bind_shortcuts()
        self.root.bind("<Configure>", self._on_window_resize)
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
        ttk.Button(top_frame, text="About", command=self.show_about).grid(row=0, column=0, sticky="w")
        right_buttons = ttk.Frame(top_frame)
        right_buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(right_buttons, text="Backup", command=self.export_backup).pack(side="left", padx=(0, 4))
        ttk.Button(right_buttons, text="Import", command=self.import_backup).pack(side="left", padx=(0, 4))
        ttk.Button(right_buttons, text="Reset", command=self.reset_all_data).pack(side="left")

        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.grid(row=1, column=0, sticky="nsew")

        left_frame = ttk.Frame(main_pane, padding=(8, 8))
        center_frame = ttk.Frame(main_pane, padding=(8, 8))
        right_frame = ttk.Frame(main_pane, padding=(8, 8))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)
        main_pane.add(left_frame, weight=1)
        main_pane.add(center_frame, weight=6)
        main_pane.add(right_frame, weight=1)

        project_label = ttk.Label(left_frame, text="Projects")
        project_label.pack(anchor="w")
        search_frame = ttk.Frame(left_frame)
        search_frame.pack(fill="x", pady=(4, 8))
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.project_search_entry = ttk.Entry(search_frame)
        self.project_search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.project_search_entry.bind("<KeyRelease>", lambda event: self.refresh_projects())

        self.project_tree = ttk.Treeview(left_frame, columns=("name", "tags"), show="headings", height=20, selectmode="extended")
        self.project_tree_base_height = 20
        self.project_tree.heading("name", text="Project Name", command=lambda: self._sort_project_tree("name"))
        self.project_tree.heading("tags", text="Tags", command=lambda: self._sort_project_tree("tags"))
        self.project_tree.column("name", width=220, anchor="w")
        self.project_tree.column("tags", width=140, anchor="w")
        self.project_tree_base_name_width = 220
        self.project_tree_base_tags_width = 140
        self.project_tree.bind("<<TreeviewSelect>>", self.on_project_select)
        self.project_tree.bind("<Button-3>", self.show_project_context_menu)
        self.project_tree.pack(fill="both", expand=True)

        self.project_context_menu = tk.Menu(self.root, tearoff=0)
        self.project_context_menu.add_command(label="Go To Folder", command=self.go_to_folder_directory)
        self.project_context_menu.add_command(label="View Project Details", command=self.view_project_details)
        self.project_context_menu.add_command(label="Edit Details", command=self.edit_project_details)
        self.project_context_menu.add_command(label="Toggle Pin", command=self.toggle_project_pin)
        self.project_context_menu.add_command(label="Bulk Edit Tags", command=self.bulk_edit_project_tags)
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(label="Delete Project Folder", command=self.delete_project_folder)

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
        ttk.Label(filter_frame, text="Note contains:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.note_filter_entry = ttk.Entry(filter_frame)
        self.note_filter_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
        self.note_filter_entry.bind("<KeyRelease>", lambda event: self.refresh_files())
        filter_frame.columnconfigure(1, weight=1)

        self.breadcrumb_label = ttk.Label(center_frame, text="Path: /")
        self.breadcrumb_label.pack(anchor="w", pady=(0, 4))
        self.file_tree = ttk.Treeview(center_frame, columns=("size", "modified"), show="tree headings", height=20, selectmode="extended")
        self.file_tree_base_height = 20
        self.file_tree.heading("#0", text="Item Name", command=lambda: self._sort_file_tree("path"))
        self.file_tree.heading("size", text="Size", command=lambda: self._sort_file_tree("size"))
        self.file_tree.heading("modified", text="Last Modified", command=lambda: self._sort_file_tree("modified"))
        self.file_tree.column("#0", width=420, anchor="w")
        self.file_tree.column("size", width=100, anchor="e")
        self.file_tree.column("modified", width=170, anchor="w")
        self.file_tree_base_name_width = 420
        self.file_tree_base_size_width = 100
        self.file_tree_base_modified_width = 170
        self.file_tree.bind("<<TreeviewSelect>>", self.on_file_select)
        self.file_tree.bind("<Double-1>", self.on_file_double_click)
        self.file_tree.bind("<Button-3>", self.show_file_context_menu)
        self.file_tree.pack(fill="both", expand=True)

        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="Add/Edit Notes", command=self.add_file_note)
        self.file_context_menu.add_command(label="Open File", command=self.open_file)
        self.file_context_menu.add_command(label="Rename File", command=self.rename_file)
        self.file_context_menu.add_command(label="Move Selected to Folder", command=self.move_selected_to_folder)
        self.file_context_menu.add_command(label="Compare to Previous Revision", command=self.compare_with_previous_snapshot)
        self.file_context_menu.add_command(label="Restore Previous Snapshot", command=self.restore_previous_snapshot)
        self.file_context_menu.add_separator()
        self.file_context_menu.add_command(label="Remove File/Folder", command=self.remove_item)

        file_buttons = ttk.Frame(center_frame)
        file_buttons.pack(fill="x", pady=(8, 0))
        self.add_files_button = ttk.Button(file_buttons, text="Add Files", command=self.add_files)
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(file_buttons, text="Add Folder", command=self.add_folder)
        self.add_folder_button.pack(side="left", padx=(4, 0))
        self.back_button = ttk.Button(file_buttons, text="Back", command=self.go_back_folder)
        self.back_button.pack(side="left", padx=(4, 0))

        self.dashboard_frame = ttk.Frame(right_frame)
        self.dashboard_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Create scrollable canvas for content sections
        self.right_scroll_canvas = tk.Canvas(right_frame, highlightthickness=0)
        self.right_scroll_canvas.grid(row=1, column=0, sticky="nsew")
        
        scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=self.right_scroll_canvas.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        
        self.right_scroll_canvas.configure(yscrollcommand=scrollbar.set)
        self.content_frame = ttk.Frame(self.right_scroll_canvas)
        self.content_window = self.right_scroll_canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        
        def on_content_configure(event: object) -> None:
            self.right_scroll_canvas.configure(scrollregion=self.right_scroll_canvas.bbox("all"))
        
        def on_canvas_configure(event: tk.Event) -> None:
            self.right_scroll_canvas.itemconfig(self.content_window, width=event.width)
        
        self.content_frame.bind("<Configure>", on_content_configure)
        self.right_scroll_canvas.bind("<Configure>", on_canvas_configure)
        self.right_scroll_canvas.bind("<MouseWheel>", lambda e: self.right_scroll_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.right_scroll_canvas.bind("<Button-4>", lambda e: self.right_scroll_canvas.yview_scroll(-1, "units"))
        self.right_scroll_canvas.bind("<Button-5>", lambda e: self.right_scroll_canvas.yview_scroll(1, "units"))

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
        self.details_text_base_width = 42
        self.details_text_base_height = 10
        self.details_text.pack(fill="both", expand=True, pady=(0, 4))
        history_label = ttk.Label(self.content_frame, text="Project Change History")
        history_label.pack(anchor="w", pady=(2, 0))
        self.history_filter_combo = ttk.Combobox(self.content_frame, state="readonly", width=20)
        self.history_filter_combo["values"] = ["ALL", "ADD", "REMOVE", "MODIFY", "MOVE", "META_UPDATE", "NOTE", "EDIT", "RENAME", "RESTORE"]
        self.history_filter_combo.set("ALL")
        self.history_filter_combo.bind("<<ComboboxSelected>>", lambda event: self._show_history())
        self.history_filter_combo.pack(anchor="w", pady=(2, 2))
        self.history_text = tk.Text(self.content_frame, height=10, wrap="word", state="disabled")
        self.history_text_base_width = 42
        self.history_text_base_height = 10
        self.history_text.pack(fill="both", expand=True, pady=(0, 4))
        history_button_frame = ttk.Frame(self.content_frame)
        history_button_frame.pack(fill="x", pady=(0, 4))
        self.view_history_button = ttk.Button(history_button_frame, text="View as Text File", command=self.print_project_history)
        self.view_history_button.pack(side="right")

        todo_label = ttk.Label(self.content_frame, text="Project Notes")
        todo_label.pack(anchor="w", pady=(2, 0))
        self.todo_listbox = tk.Listbox(self.content_frame)
        self.todo_listbox_base_height = 10
        self.todo_listbox.pack(fill="both", expand=True, pady=(0, 4))
        todo_buttons_frame = ttk.Frame(self.content_frame)
        todo_buttons_frame.pack(fill="x", pady=(0, 0))
        self.add_note_button = ttk.Button(todo_buttons_frame, text="Add Note", command=self.add_todo_item)
        self.add_note_button.pack(side="left")
        self.remove_note_button = ttk.Button(todo_buttons_frame, text="Remove Selected", command=self.remove_todo_item)
        self.remove_note_button.pack(side="left", padx=(4, 0))
        self._update_file_action_buttons_state()

    def refresh_projects(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        search_terms = [term for term in self.project_search_entry.get().strip().lower().split() if term]
        self.projects = [Project.from_dict(row) for row in self.csv.read_rows("projects")]
        self.projects.sort(key=lambda p: (p.pinned != "1", p.project_name.lower()))
        for project in self.projects:
            project_text = f"{project.project_name} {project.tags} {project.root_path}".lower()
            if search_terms and not all(term in project_text for term in search_terms):
                continue
            display_name = f"* {project.project_name}" if project.pinned == "1" else project.project_name
            self.project_tree.insert("", "end", iid=project.project_id, values=(display_name, project.tags))
        self._update_dashboard()

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

    def show_about(self) -> None:
        messagebox.showinfo(
            "About",
            f"Project File Manager\nVersion {APP_VERSION}\n\nA desktop application for organizing and tracking local project folders, files, change history, snapshots, and project notes. Everything is stored locally with no internet required.\n\nDeveloper: Bejon Minada\n\nMain repository folder:\n{self.repository_folder}",
        )

    def reset_all_data(self) -> None:
        confirm_dialog = tk.Toplevel(self.root)
        confirm_dialog.title("Reset All Data")
        confirm_dialog.transient(self.root)
        confirm_dialog.grab_set()
        confirm_dialog.geometry("420x180")
        confirm_dialog.resizable(False, False)

        ttk.Label(
            confirm_dialog,
            text="This will permanently delete ALL projects, files,\nhistory, and project folders on disk.\n\nType  CLEAR ALL DATA  to confirm:",
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
            confirm_dialog.destroy()
            # Delete all project folders on disk
            for row in self.csv.read_rows("projects"):
                folder = Path(row.get("root_path", ""))
                if folder.exists() and folder.is_dir():
                    try:
                        shutil.rmtree(folder)
                    except Exception:
                        pass
            # Clear all CSV tables
            for table in ("projects", "files", "change_log", "todos"):
                self.csv.write_rows(table, [])
            self.selected_project = None
            self.selected_file = None
            self.current_folder_rel = ""
            self.selected_item_kind = ""
            self.selected_item_rel = ""
            self.projects = []
            self.tracked_files = []
            self.project_todos.clear()
            self.refresh_projects()
            self.refresh_files()
            self.history_text.config(state="normal")
            self.history_text.delete("1.0", tk.END)
            self.history_text.config(state="disabled")
            self.todo_listbox.delete(0, tk.END)

        ttk.Button(button_frame, text="Reset", command=do_reset).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=confirm_dialog.destroy).pack(side="left")
        confirm_dialog.wait_window()

    def on_project_select(self, event: object) -> None:
        selection = self.project_tree.selection()
        if not selection:
            self.selected_project = None
            self.current_folder_rel = ""
            self._update_file_action_buttons_state()
            return
        project_id = selection[0]
        self.selected_project = next((p for p in self.projects if p.project_id == project_id), None)
        if self.selected_project:
            self.current_folder_rel = ""
            self._sync_untracked_files()
            self._load_project_todos()
            self._update_file_action_buttons_state()
        self.refresh_files()
        self._show_history()

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

    def bulk_edit_project_tags(self) -> None:
        selected_ids = list(self.project_tree.selection())
        if not selected_ids:
            messagebox.showwarning("Select projects", "Please select one or more projects.")
            return
        new_tags = simpledialog.askstring("Bulk Edit Tags", "Enter tags for selected projects:", parent=self.root)
        if new_tags is None:
            return
        project_rows = self.csv.read_rows("projects")
        selected_ids_set = set(selected_ids)
        for row in project_rows:
            if row.get("project_id") in selected_ids_set:
                old_tags = row.get("tags", "")
                row["tags"] = new_tags
                self.csv.append_row("change_log", ChangeRecord(
                    timestamp=datetime.now().isoformat(),
                    project_id=row.get("project_id", ""),
                    file_id="",
                    change_type="EDIT",
                    old_value=old_tags,
                    new_value=new_tags,
                    note="Bulk tag update.",
                ).to_dict())
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
            shutil.copytree(source_folder, destination_folder)
        except Exception as exc:
            messagebox.showerror("Copy failed", f"Unable to add folder: {exc}")
            return

        self._sync_untracked_files()
        self.refresh_files()

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
        for item_path in sorted(current_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            relative = str(item_path.relative_to(project_root)).replace("\\", "/")
            item_name = item_path.name

            if search_terms and not all(term in relative.lower() for term in search_terms):
                continue

            if item_path.is_dir():
                self.file_tree.insert("", "end", iid=f"folder::{relative}", text=item_name, image=self.tree_folder_icon, values=("", ""))
                continue

            tracked = tracked_by_rel.get(relative)
            extension = (tracked.extension if tracked else item_path.suffix.lower()) or ""
            if selected_ext and extension.lower() != selected_ext:
                continue
            if note_filter and tracked and note_filter not in (tracked.notes or "").lower():
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

    def on_file_double_click(self, event: object) -> None:
        row_id = self.file_tree.identify_row(event.y)
        if not row_id:
            return
        if row_id.startswith("folder::"):
            self.current_folder_rel = row_id.split("::", 1)[1]
            self.refresh_files()

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
            f"Notes: {self.selected_file.notes}\n"
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
            self.todo_listbox.insert(tk.END, todo.get("description", ""))

    def add_todo_item(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Add Task")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("500x200")

        ttk.Label(dialog, text=f"Add task for: {self.selected_project.project_name}").pack(anchor="w", padx=10, pady=(10, 0))
        task_text = tk.Text(dialog, wrap="word", width=60, height=6)
        task_text.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))

        def save_task() -> None:
            task = task_text.get("1.0", tk.END).strip()
            if not task:
                return
            todo_row = {
                "todo_id": self.csv.next_id("todos", "todo_id"),
                "project_id": self.selected_project.project_id,
                "description": task,
                "created_date": datetime.now().isoformat(),
            }
            self.csv.append_row("todos", todo_row)
            self._load_project_todos()
            self._show_project_todos()
            dialog.destroy()

        ttk.Button(button_frame, text="Save", command=save_task).pack(side="right")
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.wait_window()

    def remove_todo_item(self) -> None:
        if not self.selected_project:
            return
        selection = self.todo_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        todos = self.project_todos.get(self.selected_project.project_id, [])
        if not (0 <= index < len(todos)):
            return
        todo_id = todos[index].get("todo_id")
        all_todos = self.csv.read_rows("todos")
        remaining = [row for row in all_todos if not (row.get("project_id") == self.selected_project.project_id and row.get("todo_id") == todo_id)]
        self.csv.write_rows("todos", remaining)
        self._load_project_todos()
        self._show_project_todos()

    def add_file_note(self) -> None:
        if not self.selected_project or not self.selected_file:
            return

        editor = tk.Toplevel(self.root)
        editor.title("Add/Edit Notes")
        editor.transient(self.root)
        editor.grab_set()
        editor.geometry("600x320")

        ttk.Label(editor, text=f"Notes for: {self.selected_file.relative_path}").pack(anchor="w", padx=10, pady=(10, 0))
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
            return
        self.file_tree.selection_set(file_id)
        self.file_tree.focus(file_id)
        self.on_file_select(None)
        try:
            self.file_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.file_context_menu.grab_release()

    def move_selected_to_folder(self) -> None:
        if not self.selected_project:
            return
        selection = [item for item in self.file_tree.selection() if item.startswith("file::")]
        if not selection:
            messagebox.showwarning("Select files", "Please select one or more files.")
            return
        target_rel = simpledialog.askstring("Move Selected", "Enter destination folder (relative to project root):", parent=self.root)
        if target_rel is None:
            return
        target_rel = target_rel.strip().strip("/")
        project_root = Path(self.selected_project.root_path)
        target_dir = project_root / Path(target_rel) if target_rel else project_root
        target_dir.mkdir(parents=True, exist_ok=True)
        file_rows = self.csv.read_rows("files")
        for selected in selection:
            rel = selected.split("::", 1)[1]
            source = project_root / Path(rel)
            if not source.exists():
                continue
            dest = target_dir / source.name
            if dest.exists():
                continue
            source.rename(dest)
            new_rel = str(dest.relative_to(project_root)).replace("\\", "/")
            for row in file_rows:
                if row.get("project_id") == self.selected_project.project_id and row.get("relative_path") == rel:
                    row["relative_path"] = new_rel
                    row["last_modified"] = datetime.fromtimestamp(dest.stat().st_mtime).isoformat()
                    row["checksum"] = compute_checksum(dest)
                    break
            self.csv.append_row("change_log", ChangeRecord(
                timestamp=datetime.now().isoformat(),
                project_id=self.selected_project.project_id,
                file_id="",
                change_type="MOVE",
                old_value=rel,
                new_value=new_rel,
                note="Bulk move file.",
            ).to_dict())
        self.csv.write_rows("files", file_rows)
        self.refresh_files()

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

    def compare_with_previous_snapshot(self) -> None:
        if not self.selected_project or not self.selected_file:
            return
        snapshots = self._list_snapshots_for_relative(
            self.selected_project.project_id, self.selected_file.relative_path
        )
        if len(snapshots) < 2:
            messagebox.showinfo("Compare", "Not enough revisions to compare. Save more changes first.")
            return

        current_file = Path(self.selected_project.root_path) / Path(self.selected_file.relative_path)
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
        curr_label = f"Current  ({self._format_datetime_readable(datetime.fromtimestamp(curr_stat.st_mtime).isoformat()) if curr_stat else 'missing'}  {curr_stat.st_size:,} B if curr_stat else '')"
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
        curr_label_text = f"Current  ({self._format_datetime_readable(datetime.fromtimestamp(curr_stat.st_mtime).isoformat()) if curr_stat else 'missing'}  {curr_stat.st_size:,} B if curr_stat else '')"
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

    def restore_previous_snapshot(self) -> None:
        if not self.selected_project or not self.selected_file:
            return
        snapshots = self._list_snapshots_for_relative(self.selected_project.project_id, self.selected_file.relative_path)
        if len(snapshots) < 2:
            messagebox.showinfo("Restore", "No previous snapshot available.")
            return
        previous_snapshot = snapshots[-2]
        target_file = Path(self.selected_project.root_path) / Path(self.selected_file.relative_path)
        if not messagebox.askyesno("Restore", "Restore the previous snapshot for this file?"):
            return
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(previous_snapshot, target_file)
        except Exception as exc:
            messagebox.showerror("Restore failed", f"Could not restore snapshot: {exc}")
            return
        self.csv.append_row("change_log", ChangeRecord(
            timestamp=datetime.now().isoformat(),
            project_id=self.selected_project.project_id,
            file_id=self.selected_file.file_id,
            change_type="RESTORE",
            old_value="",
            new_value=self.selected_file.relative_path,
            note="Restored previous snapshot.",
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
            return f"Restored previous snapshot for '{new_value or old_value or file_id}'."
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

            # Rename folder on disk if name changed
            old_folder = Path(proj.root_path)
            new_folder = old_folder.parent / new_name
            if new_name != proj.project_name:
                if new_folder.exists():
                    messagebox.showwarning("Name conflict", f"A folder named '{new_name}' already exists.", parent=form)
                    return
                try:
                    old_folder.rename(new_folder)
                except Exception as exc:
                    messagebox.showerror("Rename failed", f"Could not rename folder: {exc}", parent=form)
                    return

            timestamp = datetime.now().isoformat()
            if new_name != proj.project_name:
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
                    row["root_path"] = str(new_folder) if new_name != proj.project_name else proj.root_path
                    break
            self.csv.write_rows("projects", project_rows)

            proj.project_name = new_name
            proj.description = new_description
            proj.tags = new_tags
            if new_name != proj.project_name:
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
                    self._move_to_recycle(folder_path)
                except Exception as exc:
                    messagebox.showerror("Remove failed", f"Could not remove folder {folder_path}: {exc}")
                    return

        updated_rows = []
        for row in file_rows:
            rel_path = row.get("relative_path", "")
            if rel_path in delete_rel_paths:
                file_path = project_root / Path(rel_path)
                if file_path.exists():
                    try:
                        self._move_to_recycle(file_path)
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
        self.selected_file = None
        self.selected_item_kind = ""
        self.selected_item_rel = ""
        self.refresh_files()

    def delete_project_folder(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        if not messagebox.askyesno("Delete project folder", f"Delete project '{self.selected_project.project_name}' and its folder? This will remove all tracked files and delete the folder on disk."):
            return
        project_root = Path(self.selected_project.root_path)
        project_id = self.selected_project.project_id
        file_rows = self.csv.read_rows("files")
        project_files = [row for row in file_rows if row.get("project_id") == project_id]
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
        remaining_files = [row for row in file_rows if row.get("project_id") != project_id]
        self.csv.write_rows("files", remaining_files)
        project_rows = self.csv.read_rows("projects")
        remaining_projects = [row for row in project_rows if row.get("project_id") != project_id]
        self.csv.write_rows("projects", remaining_projects)
        if project_root.exists() and project_root.is_dir():
            try:
                self._move_to_recycle(project_root)
            except Exception as exc:
                messagebox.showwarning("Delete folder", f"Could not delete folder on disk: {exc}")
        self.selected_project = None
        self.selected_file = None
        self.refresh_projects()
        self.refresh_files()

    def _auto_sync_repository(self) -> None:
        """On startup: remove projects whose folder is gone and register any new
        subfolders found inside the repository directory."""
        repo = self.repository_folder
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

        # Register new subfolders in the repository that are not yet tracked
        tracked_paths = {Path(row.get("root_path", "")).resolve() for row in valid_rows}
        for subfolder in sorted(repo.iterdir()):
            if not subfolder.is_dir():
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
        selected_project_id = self.selected_project.project_id if self.selected_project else None

        self._auto_sync_repository()
        project_rows = self.csv.read_rows("projects")
        all_file_rows = self.csv.read_rows("files")
        updated_all_rows: List[dict] = []

        max_file_id = 0
        for row in all_file_rows:
            try:
                max_file_id = max(max_file_id, int(row.get("file_id", "0")))
            except ValueError:
                continue

        for project_row in project_rows:
            project_id = project_row.get("project_id", "")
            root_folder = Path(project_row.get("root_path", ""))
            if not root_folder.exists() or not root_folder.is_dir():
                continue

            scanned = list(scan_project_files(root_folder))
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

    def export_backup(self) -> None:
        destination = filedialog.asksaveasfilename(
            title="Export Backup",
            defaultextension=".zip",
            filetypes=[("ZIP files", "*.zip")],
        )
        if not destination:
            return
        try:
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                for name in ("projects.csv", "files.csv", "change_log.csv", "todos.csv"):
                    path = self.csv.base_dir / name
                    if path.exists():
                        archive.write(path, arcname=name)
                for folder_name in ("repository", "snapshots", "recycle_bin"):
                    folder = Path(__file__).resolve().parent / folder_name
                    if folder.exists():
                        for child in folder.rglob("*"):
                            if child.is_file():
                                archive.write(child, arcname=str(child.relative_to(Path(__file__).resolve().parent)).replace("\\", "/"))
            messagebox.showinfo("Backup", "Backup exported successfully.")
        except Exception as exc:
            messagebox.showerror("Backup", f"Backup export failed: {exc}")

    def import_backup(self) -> None:
        source = filedialog.askopenfilename(title="Import Backup", filetypes=[("ZIP files", "*.zip")])
        if not source:
            return
        if not messagebox.askyesno("Import Backup", "Importing will overwrite current local data. Continue?"):
            return
        base = Path(__file__).resolve().parent
        try:
            with zipfile.ZipFile(source, "r") as archive:
                archive.extractall(base)
            self._auto_sync_repository()
            self.refresh_projects()
            self.refresh_files()
            self._show_history()
            messagebox.showinfo("Import", "Backup imported successfully.")
        except Exception as exc:
            messagebox.showerror("Import", f"Backup import failed: {exc}")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-f>", lambda event: self._focus_file_search())
        self.root.bind("<Control-n>", lambda event: self.add_project())
        self.root.bind("<F5>", lambda event: self.refresh_repository())
        self.root.bind("<Alt-Left>", lambda event: self.go_back_folder())

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

        # Scale tree view column widths and row heights
        scaled_name_width = int(self.project_tree_base_name_width * self.scale_factor)
        scaled_tags_width = int(self.project_tree_base_tags_width * self.scale_factor)

        self.project_tree.column("name", width=scaled_name_width)
        self.project_tree.column("tags", width=scaled_tags_width)

        scaled_file_name = int(self.file_tree_base_name_width * self.scale_factor)
        scaled_file_size = int(self.file_tree_base_size_width * self.scale_factor)
        scaled_file_modified = int(self.file_tree_base_modified_width * self.scale_factor)
        self.file_tree.column("#0", width=scaled_file_name)
        self.file_tree.column("size", width=scaled_file_size)
        self.file_tree.column("modified", width=scaled_file_modified)

        # Scale text widget dimensions and fonts
        new_details_height = max(4, int(self.details_text_base_height * self.scale_factor))
        new_history_height = max(4, int(self.history_text_base_height * self.scale_factor))
        new_todo_height = max(4, int(self.todo_listbox_base_height * self.scale_factor))

        self.details_text.config(height=new_details_height, font=("TkDefaultFont", scaled_font_size))
        self.history_text.config(height=new_history_height, font=("TkDefaultFont", scaled_font_size))
        self.todo_listbox.config(height=new_todo_height, font=("TkDefaultFont", scaled_font_size))

        # Scale dashboard canvas heights
        scaled_activity_height = max(30, int(38 * self.scale_factor))
        scaled_top_height = max(30, int(44 * self.scale_factor))
        self.dash_activity_canvas.config(height=scaled_activity_height)
        self.dash_top_canvas.config(height=scaled_top_height)

        # Redraw dashboard with new dimensions
        self._update_dashboard()

    def _move_to_recycle(self, path: Path) -> None:
        self.recycle_bin_folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = self.recycle_bin_folder / f"{stamp}_{path.name}"
        shutil.move(str(path), str(destination))

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
        existing = [p for p in snapshot_dir.iterdir() if p.is_file() and f"__{checksum}" in p.name]
        if existing:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = file_path.suffix or ".bin"
        target = snapshot_dir / f"{stamp}__{checksum}{ext}"
        shutil.copy2(file_path, target)

    def _update_dashboard(self) -> None:
        projects = self.csv.read_rows("projects")
        files = self.csv.read_rows("files")
        changes = self.csv.read_rows("change_log")
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
