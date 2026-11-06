"""Backup and restore for the SQLite database plus all stored files.

A backup is one .zip file containing:
  database/app.db   a consistent copy of the database
  files/...         uploaded previous reports and generated Word files
  MANIFEST.txt      date and file count (no personal data)
The zip contains information about children. Protect it like the application itself.
"""
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath


class BackupError(Exception):
    """Message is safe to show to the user."""


def create_backup(db_path, upload_folder, backups_dir):
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BackupError("The database file was not found, so there is nothing to back up.")
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"backup-{stamp}.zip"
    counter = 1
    while target.exists():  # two backups in the same second must not overwrite each other
        counter += 1
        target = backups_dir / f"backup-{stamp}-{counter}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "app.db"
        source = sqlite3.connect(str(db_path))
        dest = sqlite3.connect(str(copy_path))
        try:
            source.backup(dest)  # safe even while the app is using the database
        finally:
            dest.close()
            source.close()
        count = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy_path, "database/app.db")
            base = Path(upload_folder)
            if base.is_dir():
                for f in sorted(base.rglob("*")):
                    if f.is_file():
                        z.write(f, "files/" + f.relative_to(base).as_posix())
                        count += 1
            z.writestr("MANIFEST.txt",
                       "Happy Children Nepal report app backup\n"
                       f"created: {datetime.now().isoformat(timespec='seconds')}\n"
                       f"files: {count}\n")
    return target


def _check_names(names):
    for name in names:
        p = PurePosixPath(name.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
            raise BackupError("This backup file contains unsafe file names and was not used.")


def restore_backup(zip_path, db_path, upload_folder):
    """Replaces the database and all stored files with the contents of the backup.
    Everything is checked BEFORE anything is overwritten."""
    try:
        z = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, FileNotFoundError, OSError):
        raise BackupError("This is not a readable backup file.")
    with z:
        names = z.namelist()
        _check_names(names)
        if "database/app.db" not in names:
            raise BackupError("This zip file is not a backup of this application (no database inside).")

        with tempfile.TemporaryDirectory() as tmp:
            staged_db = Path(tmp) / "app.db"
            with z.open("database/app.db") as src, open(staged_db, "wb") as out:
                shutil.copyfileobj(src, out)
            try:
                conn = sqlite3.connect(str(staged_db))
                try:
                    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                finally:
                    conn.close()
            except sqlite3.DatabaseError:
                raise BackupError("The database inside this backup is damaged. Nothing was changed.")
            if ok != "ok" or "users" not in tables or "children" not in tables:
                raise BackupError("The database inside this backup is damaged or from another "
                                  "application. Nothing was changed.")

            # ---- everything checked: now replace ----
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged_db, db_path)

            base = Path(upload_folder)
            if base.exists():
                shutil.rmtree(base)
            base.mkdir(parents=True, exist_ok=True)
            restored = 0
            for name in names:
                if name.startswith("files/") and not name.endswith("/"):
                    dest = base / Path(*PurePosixPath(name[len("files/"):]).parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(name) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
                    restored += 1
    return restored
