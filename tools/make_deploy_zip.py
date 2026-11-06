"""Makes happy-report-app-deploy.zip: only the files the web host needs.

Left out on purpose: your virtual environment, your secret .env file, your database,
uploaded files, backups, test files and Git history.
Run from the project folder:  python tools/make_deploy_zip.py
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_NAME = "happy-report-app-deploy.zip"
SKIP_DIRS = {"venv", ".venv", ".git", "instance", "__pycache__", "tests", "backups", "uploads",
             ".pytest_cache", "node_modules"}
SKIP_FILES = {".env", OUT_NAME, "pytest.ini"}
SKIP_SUFFIXES = {".pyc", ".db", ".sqlite", ".zip", ".log"}


def collect():
    found = []
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]  # never even look inside these
        for name in files:
            path = Path(folder) / name
            if name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
                continue
            found.append(path)
    return sorted(found)


def main():
    files = collect()
    if not any(p.name == "wsgi.py" for p in files):
        sys.exit("wsgi.py is missing. Is this the project folder?")
    target = ROOT / OUT_NAME
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
    print(f"Created {target} with {len(files)} files.")
    print("It does NOT contain .env, your database or any uploaded files.")


if __name__ == "__main__":
    main()
