import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional

from change_detector import detect_changes
from csv_manager import CSVManager
from file_scanner import scan_project_files
from models import ChangeRecord, Project, TrackedFile

APP_VERSION = "1.0"

def _format_recent_date(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat()

class DocumentTrackerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Project File Manager")
        self.folder_icon = tk.PhotoImage(width=16, height=16)
        self.folder_icon.put("#f7c600", to=(0, 5, 15, 15))
        self.folder_icon.put("#e0a800", to=(0, 3, 10, 7))
        self.folder_icon.put("#d18b00", to=(0, 0, 15, 4))
        self.root.iconphoto(False, self.folder_icon)
        self.csv = CSVManager()
        self.repository_folder = Path(__file__).resolve().parent / "repository"
        self.repository_folder.mkdir(parents=True, exist_ok=True)
        self.projects: List[Project] = []
        self.tracked_files: List[TrackedFile] = []
        self.change_rows: List[ChangeRecord] = []
        self.selected_project: Optional[Project] = None
        self.selected_file: Optional[TrackedFile] = None
        self.selected_file_ids: List[str] = []
        self.sort_state = {
            "projects": {"name": False, "tags": False},
            "files": {"path": False, "size": False, "modified": False},
        }
        self.project_todos: dict[str, List[dict]] = {}
        self._build_ui()
        self._auto_sync_repository()
        self.refresh_projects()

    def _build_ui(self) -> None:
        self.root.geometry("1200x700")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top_frame = ttk.Frame(self.root, padding=(8, 4))
        top_frame.grid(row=0, column=0, sticky="ew")
        top_frame.columnconfigure(1, weight=1)
        ttk.Button(top_frame, text="About", command=self.show_about).grid(row=0, column=0, sticky="w")
        ttk.Button(top_frame, text="Reset", command=self.reset_all_data).grid(row=0, column=2, sticky="e")

        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.grid(row=1, column=0, sticky="nsew")

        left_frame = ttk.Frame(main_pane, padding=(8, 8))
        center_frame = ttk.Frame(main_pane, padding=(8, 8))
        right_frame = ttk.Frame(main_pane, padding=(8, 8))
        right_frame.columnconfigure(0, weight=1)
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

        self.project_tree = ttk.Treeview(left_frame, columns=("name", "tags"), show="headings", height=20, selectmode="browse")
        self.project_tree.heading("name", text="Project Name", command=lambda: self._sort_project_tree("name"))
        self.project_tree.heading("tags", text="Tags", command=lambda: self._sort_project_tree("tags"))
        self.project_tree.column("name", width=220, anchor="w")
        self.project_tree.column("tags", width=140, anchor="w")
        self.project_tree.bind("<<TreeviewSelect>>", self.on_project_select)
        self.project_tree.bind("<Button-3>", self.show_project_context_menu)
        self.project_tree.pack(fill="both", expand=True)

        self.project_context_menu = tk.Menu(self.root, tearoff=0)
        self.project_context_menu.add_command(label="Go To Folder", command=self.go_to_folder_directory)
        self.project_context_menu.add_command(label="View Project Details", command=self.view_project_details)
        self.project_context_menu.add_command(label="Edit Details", command=self.edit_project_details)
        self.project_context_menu.add_separator()
        self.project_context_menu.add_command(label="Remove Project Folder", command=self.remove_project)
        self.project_context_menu.add_command(label="Delete Project Folder", command=self.delete_project_folder)

        project_buttons = ttk.Frame(left_frame)
        project_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(project_buttons, text="Add Project", command=self.add_project).pack(side="left")

        file_label = ttk.Label(center_frame, text="Tracked Files")
        file_label.pack(anchor="w")
        filter_frame = ttk.Frame(center_frame)
        filter_frame.pack(fill="x", pady=(4, 8))
        ttk.Label(filter_frame, text="Search filename:").grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(filter_frame)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(filter_frame, text="Extension:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.extension_combo = ttk.Combobox(filter_frame, width=12, state="readonly")
        self.extension_combo.grid(row=0, column=3, sticky="w", padx=4)
        self.extension_combo['values'] = [""]
        ttk.Button(filter_frame, text="Apply", command=self.refresh_files).grid(row=0, column=4, sticky="e", padx=(10, 0))
        filter_frame.columnconfigure(1, weight=1)
        self.file_tree = ttk.Treeview(center_frame, columns=("path", "size", "modified"), show="headings", height=20, selectmode="extended")
        self.file_tree.heading("path", text="Relative Path", command=lambda: self._sort_file_tree("path"))
        self.file_tree.heading("size", text="Size", command=lambda: self._sort_file_tree("size"))
        self.file_tree.heading("modified", text="Last Modified", command=lambda: self._sort_file_tree("modified"))
        self.file_tree.column("path", width=420, anchor="w")
        self.file_tree.column("size", width=100, anchor="e")
        self.file_tree.column("modified", width=170, anchor="w")
        self.file_tree.bind("<<TreeviewSelect>>", self.on_file_select)
        self.file_tree.bind("<Button-3>", self.show_file_context_menu)
        self.file_tree.pack(fill="both", expand=True)

        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="Add/Edit Notes", command=self.add_file_note)
        self.file_context_menu.add_command(label="Open File", command=self.open_file)
        self.file_context_menu.add_command(label="Rename File", command=self.rename_file)
        self.file_context_menu.add_separator()
        self.file_context_menu.add_command(label="Delete File", command=self.delete_file)

        file_buttons = ttk.Frame(center_frame)
        file_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(file_buttons, text="Add Files", command=self.add_files).pack(side="left")
        ttk.Button(file_buttons, text="Refresh", command=self.refresh_files).pack(side="left", padx=(4, 0))

        detail_label = ttk.Label(right_frame, text="File Details")
        detail_label.pack(anchor="w")
        self.details_text = tk.Text(right_frame, width=42, height=10, wrap="word", state="disabled")
        self.details_text.pack(fill="x", expand=False)
        history_label = ttk.Label(right_frame, text="Project Change History")
        history_label.pack(anchor="w", pady=(8, 0))
        self.history_text = tk.Text(right_frame, width=42, height=10, wrap="word", state="disabled")
        self.history_text.pack(fill="x", expand=False)
        history_button_frame = ttk.Frame(right_frame)
        history_button_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(history_button_frame, text="View as Text File", command=self.print_project_history).pack(side="right")

        todo_label = ttk.Label(right_frame, text="Project Notes")
        todo_label.pack(anchor="w", pady=(10, 0))
        self.todo_listbox = tk.Listbox(right_frame, height=10)
        self.todo_listbox.pack(fill="both", expand=True, pady=(4, 0))
        todo_buttons_frame = ttk.Frame(right_frame)
        todo_buttons_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(todo_buttons_frame, text="Add Note", command=self.add_todo_item).pack(side="left")
        ttk.Button(todo_buttons_frame, text="Remove Selected", command=self.remove_todo_item).pack(side="left", padx=(4, 0))

    def refresh_projects(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        search_terms = [term for term in self.project_search_entry.get().strip().lower().split() if term]
        self.projects = [Project.from_dict(row) for row in self.csv.read_rows("projects")]
        for project in self.projects:
            project_text = f"{project.project_name} {project.tags} {project.root_path}".lower()
            if search_terms and not all(term in project_text for term in search_terms):
                continue
            self.project_tree.insert("", "end", iid=project.project_id, values=(project.project_name, project.tags))

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
            f"Project File Manager\nVersion {APP_VERSION}\n\nA desktop application for organizing and tracking local project folders, files, change history, notes, and tasks — all stored locally with no internet required.\n\nDeveloper: Bejon Minada\n\nMain repository folder:\n{self.repository_folder}",
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
            self.projects = []
            self.tracked_files = []
            self.refresh_projects()
            self.refresh_files()

        ttk.Button(button_frame, text="Reset", command=do_reset).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="Cancel", command=confirm_dialog.destroy).pack(side="left")
        confirm_dialog.wait_window()

    def on_project_select(self, event: object) -> None:
        selection = self.project_tree.selection()
        if not selection:
            self.selected_project = None
            return
        project_id = selection[0]
        self.selected_project = next((p for p in self.projects if p.project_id == project_id), None)
        if self.selected_project:
            self._sync_untracked_files()
            self._load_project_todos()
        self.refresh_files()
        self._show_history()

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

            checksum = self._compute_file_checksum(destination_path)
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
        self.refresh_files()

    def _compute_file_checksum(self, path: Path) -> str:
        from file_scanner import compute_checksum
        return compute_checksum(path)

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

    def _update_file_command_state(self) -> None:
        # File tree actions are now exposed via right-click context menu.
        # This method remains for compatibility with selection handling.
        _ = self.file_tree.selection()

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
            return
        self._sync_untracked_files()
        files = [TrackedFile.from_dict(row) for row in self.csv.read_rows("files") if row.get("project_id") == self.selected_project.project_id]
        self.tracked_files = files
        extensions = sorted({file.extension for file in files if file.extension})
        self.extension_combo['values'] = [""] + extensions
        selected_ext = self.extension_combo.get().strip().lower()
        search_terms = [term for term in self.search_entry.get().strip().lower().split() if term]
        for file in files:
            if search_terms and not all(term in file.relative_path.lower() for term in search_terms):
                continue
            if selected_ext and file.extension.lower() != selected_ext:
                continue
            formatted_modified = self._format_datetime_readable(file.last_modified)
            self.file_tree.insert("", "end", iid=file.file_id, values=(file.relative_path, file.file_size, formatted_modified))
        self.selected_file = None
        self._update_file_command_state()

    def on_file_select(self, event: object) -> None:
        selection = self.file_tree.selection()
        if not selection or not self.selected_project:
            self.selected_file = None
            self._update_file_command_state()
            return
        if len(selection) == 1:
            file_id = selection[0]
            self.selected_file = next((f for f in self.tracked_files if f.file_id == file_id), None)
            self._show_file_details()
            self._show_history()
        else:
            self.selected_file = None
            self.details_text.delete("1.0", tk.END)
            self.history_text.delete("1.0", tk.END)
        self._update_file_command_state()

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
        for row in change_rows[-50:]:
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
        return f"{change_type} for file '{new_value or old_value or file_id}': {note}"

    def _sort_treeview(self, tree: ttk.Treeview, col: str, reverse: bool) -> bool:
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

    def _save_history_pdf(self, destination: str, title: str, lines: List[str]) -> None:
        page_width = 595.28
        page_height = 841.89
        margin = 40
        font_size = 12
        line_height = 14
        max_lines_per_page = int((page_height - 2 * margin - 40) // line_height)
        pages = [lines[i:i + max_lines_per_page] for i in range(0, len(lines), max_lines_per_page)]

        def pdf_escape(text: str) -> str:
            return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        objects = [b"1 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"]
        page_refs = []
        obj_id = 2

        for page_lines in pages:
            content_id = obj_id
            obj_id += 1
            bodies = ["BT", f"/F1 {font_size} Tf", f"{margin} {page_height - margin - font_size} Td"]
            for line in page_lines:
                bodies.append(f"({pdf_escape(line)}) Tj")
                bodies.append("T*")
            bodies.append("ET")
            stream = "\n".join(bodies).encode("utf-8")
            header = f"{content_id} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("utf-8")
            objects.append(header + stream + b"\nendstream\nendobj\n")

            page_id = obj_id
            page_refs.append(page_id)
            objects.append(
                f"{page_id} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] /Contents {content_id} 0 R /Resources << /Font << /F1 0 0 R >> >> >>\nendobj\n".encode("utf-8")
            )
            obj_id += 1

        kids = " ".join(f"{page_id} 0 R" for page_id in page_refs)
        pages_object = f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>\nendobj\n".encode("utf-8")
        objects.insert(1, pages_object)

        with open(destination, "wb") as pdf_file:
            pdf_file.write(b"%PDF-1.3\n")
            offsets = [0]
            position = len(b"%PDF-1.3\n")
            for obj in objects:
                offsets.append(position)
                pdf_file.write(obj)
                position += len(obj)
            xref_position = position
            pdf_file.write(f"xref\n0 {len(offsets)}\n".encode("utf-8"))
            pdf_file.write(b"0000000000 65535 f \n")
            for offset in offsets[1:]:
                pdf_file.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
            pdf_file.write(f"trailer\n<< /Size {len(offsets)} /Root 2 0 R >>\nstartxref\n".encode("utf-8"))
            pdf_file.write(f"{xref_position}\n%%EOF\n".encode("utf-8"))

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
                row["checksum"] = self._compute_file_checksum(new_path)
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

    def delete_file(self) -> None:
        if not self.selected_project:
            return
        selection = self.file_tree.selection()
        if not selection:
            return
        if not messagebox.askyesno("Delete files", f"Delete {len(selection)} selected file(s) from disk and tracking?"):
            return
        file_rows = self.csv.read_rows("files")
        delete_ids = set(selection)
        updated_rows = []
        for row in file_rows:
            if row.get("file_id") in delete_ids:
                file_path = Path(self.selected_project.root_path) / Path(row.get("relative_path", ""))
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as exc:
                        messagebox.showerror("Delete failed", f"Could not delete file {file_path}: {exc}")
                        return
                change = ChangeRecord(
                    timestamp=datetime.now().isoformat(),
                    project_id=self.selected_project.project_id,
                    file_id=row.get("file_id", ""),
                    change_type="REMOVE",
                    old_value=row.get("relative_path", ""),
                    new_value="",
                    note="Deleted file from project and tracking.",
                )
                self.csv.append_row("change_log", change.to_dict())
            else:
                updated_rows.append(row)
        self.csv.write_rows("files", updated_rows)
        self.selected_file = None
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
                shutil.rmtree(project_root)
            except Exception as exc:
                messagebox.showwarning("Delete folder", f"Could not delete folder on disk: {exc}")
        self.selected_project = None
        self.selected_file = None
        self.refresh_projects()
        self.refresh_files()

    def remove_project(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        if not messagebox.askyesno("Remove project", f"Remove project '{self.selected_project.project_name}' from tracking without deleting its folder?"):
            return
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
                note="Project untracked without deleting folder.",
            )
            self.csv.append_row("change_log", change.to_dict())
        remaining_files = [row for row in file_rows if row.get("project_id") != project_id]
        self.csv.write_rows("files", remaining_files)
        project_rows = self.csv.read_rows("projects")
        remaining_projects = [row for row in project_rows if row.get("project_id") != project_id]
        self.csv.write_rows("projects", remaining_projects)
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
                created_date=datetime.now().isoformat(),
                last_scanned_date="",
            )
            self.csv.append_row("projects", project.to_dict())

    def rescan_project(self) -> None:
        if not self.selected_project:
            messagebox.showwarning("Select project", "Please select a project first.")
            return
        root_folder = Path(self.selected_project.root_path)
        if not root_folder.exists():
            messagebox.showerror("Missing folder", "Project root folder does not exist.")
            return
        scanned = list(scan_project_files(root_folder))
        tracked = [TrackedFile.from_dict(row) for row in self.csv.read_rows("files") if row.get("project_id") == self.selected_project.project_id]
        changes = detect_changes(self.selected_project.project_id, tracked, scanned)
        for record in changes:
            self.csv.append_row("change_log", record.to_dict())

        file_rows = self.csv.read_rows("files")
        scan_by_rel = {row["relative_path"]: row for row in scanned}
        scan_by_checksum = {row["checksum"]: row for row in scanned}
        for row in file_rows:
            if row.get("project_id") != self.selected_project.project_id:
                continue
            relative = row.get("relative_path", "")
            if relative in scan_by_rel:
                current = scan_by_rel[relative]
            elif row.get("checksum") in scan_by_checksum:
                current = scan_by_checksum[row.get("checksum")]
            else:
                continue
            row["relative_path"] = current["relative_path"]
            row["extension"] = current["extension"]
            row["file_size"] = current["file_size"]
            row["last_modified"] = current["last_modified"]
            row["checksum"] = current["checksum"]
        self.csv.write_rows("files", file_rows)

        project_rows = self.csv.read_rows("projects")
        for row in project_rows:
            if row["project_id"] == self.selected_project.project_id:
                row["last_scanned_date"] = datetime.now().isoformat()
        self.csv.write_rows("projects", project_rows)
        self.refresh_projects()
        self.refresh_files()
        self._show_history()
