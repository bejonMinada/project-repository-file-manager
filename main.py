import tkinter as tk

from ui import DocumentTrackerApp


def main() -> None:
    root = tk.Tk()
    app = DocumentTrackerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
