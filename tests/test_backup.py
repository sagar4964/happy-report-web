"""Backup and restore tests with fictional data. No Flask needed."""
import sqlite3
import zipfile
import pytest
from app.backup import create_backup, restore_backup, BackupError


def make_db(path, names=("Asha Testperson",)):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE children (id INTEGER PRIMARY KEY, name TEXT)")
    for n in names:
        conn.execute("INSERT INTO children (name) VALUES (?)", (n,))
    conn.commit()
    conn.close()


def children(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT name FROM children ORDER BY id")]
    finally:
        conn.close()


def setup(tmp_path):
    db = tmp_path / "instance" / "app.db"
    db.parent.mkdir()
    make_db(db)
    uploads = tmp_path / "instance" / "uploads"
    (uploads / "historical").mkdir(parents=True)
    (uploads / "historical" / "a.docx").write_bytes(b"original upload")
    return db, uploads, tmp_path / "instance" / "backups"


def test_backup_contains_a_database_copy_and_all_files(tmp_path):
    db, uploads, backups = setup(tmp_path)
    zip_path = create_backup(db, uploads, backups)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    assert "database/app.db" in names and "files/historical/a.docx" in names and "MANIFEST.txt" in names


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    db, uploads, backups = setup(tmp_path)
    first = create_backup(db, uploads, backups)
    second = create_backup(db, uploads, backups)
    assert first != second and first.exists() and second.exists()


def test_restore_brings_back_the_old_state(tmp_path):
    db, uploads, backups = setup(tmp_path)
    zip_path = create_backup(db, uploads, backups)
    make_db(tmp_path / "other.db", names=("Someone New",))
    conn = sqlite3.connect(str(db))
    conn.execute("DELETE FROM children")
    conn.execute("INSERT INTO children (name) VALUES ('Changed After Backup')")
    conn.commit()
    conn.close()
    (uploads / "historical" / "a.docx").write_bytes(b"changed")
    (uploads / "historical" / "extra.docx").write_bytes(b"added later")

    restored = restore_backup(zip_path, db, uploads)
    assert restored == 1
    assert children(db) == ["Asha Testperson"]
    assert (uploads / "historical" / "a.docx").read_bytes() == b"original upload"
    assert not (uploads / "historical" / "extra.docx").exists()


def test_a_backup_with_unsafe_names_is_refused_and_nothing_changes(tmp_path):
    db, uploads, backups = setup(tmp_path)
    good = create_backup(db, uploads, backups)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(evil, "w") as out:
        for name in src.namelist():
            out.writestr(name, src.read(name))
        out.writestr("../escaped.txt", "bad")
    with pytest.raises(BackupError):
        restore_backup(evil, db, uploads)
    assert children(db) == ["Asha Testperson"]
    assert not (tmp_path / "escaped.txt").exists()


def test_a_zip_without_a_database_is_refused(tmp_path):
    db, uploads, _ = setup(tmp_path)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(BackupError):
        restore_backup(bad, db, uploads)
    assert (uploads / "historical" / "a.docx").exists()


def test_a_damaged_or_foreign_database_is_refused(tmp_path):
    db, uploads, _ = setup(tmp_path)
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as z:
        z.writestr("database/app.db", b"this is not a database at all" * 50)
    with pytest.raises(BackupError):
        restore_backup(junk, db, uploads)
    foreign = tmp_path / "foreign.zip"
    other = tmp_path / "foreign.db"
    conn = sqlite3.connect(str(other))
    conn.execute("CREATE TABLE something_else (x)")
    conn.commit()
    conn.close()
    with zipfile.ZipFile(foreign, "w") as z:
        z.write(other, "database/app.db")
    with pytest.raises(BackupError):
        restore_backup(foreign, db, uploads)
    assert children(db) == ["Asha Testperson"]


def test_not_a_zip_and_missing_database_are_explained(tmp_path):
    db, uploads, backups = setup(tmp_path)
    notzip = tmp_path / "notes.zip"
    notzip.write_text("hello")
    with pytest.raises(BackupError):
        restore_backup(notzip, db, uploads)
    with pytest.raises(BackupError):
        create_backup(tmp_path / "missing.db", uploads, backups)
