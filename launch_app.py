import subprocess
import sys
import venv
from pathlib import Path

MIN_PYTHON_VERSION = (3, 10)
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
RUNTIME_FOLDERS = ("repository", "snapshots", "recycle_bin")


def ensure_runtime_folders() -> None:
    for folder_name in RUNTIME_FOLDERS:
        (PROJECT_ROOT / folder_name).mkdir(parents=True, exist_ok=True)


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON_VERSION:
        raise SystemExit(
            f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or newer is required. "
            f"Detected Python {sys.version_info.major}.{sys.version_info.minor}."
        )


def create_virtualenv() -> Path:
    if not VENV_DIR.exists():
        print("Creating virtual environment...")
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(VENV_DIR)
    python_exe = VENV_DIR / "Scripts" / "python.exe" if sys.platform.startswith("win") else VENV_DIR / "bin" / "python"
    if not python_exe.exists():
        raise SystemExit("Virtual environment creation failed.")
    return python_exe


def read_requirements() -> list[str]:
    if not REQUIREMENTS_FILE.exists():
        return []
    lines = [line.strip() for line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def install_requirements(python_exe: Path) -> None:
    requirements = read_requirements()
    if not requirements:
        return
    print("Installing required packages...")
    subprocess.run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python_exe), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)], check=True)


def run_application(python_exe: Path) -> int:
    app_script = PROJECT_ROOT / "main.py"
    return subprocess.run([str(python_exe), str(app_script)]).returncode


def main() -> None:
    ensure_runtime_folders()
    check_python_version()
    python_exe = create_virtualenv()
    if Path(sys.executable).resolve() != python_exe.resolve():
        install_requirements(python_exe)
        print("Launching Project Repository File Manager...")
        raise SystemExit(run_application(python_exe))

    # Running inside the virtual environment already.
    from main import main as start_app

    install_requirements(python_exe)
    start_app()


if __name__ == "__main__":
    main()
