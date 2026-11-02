import io
import os
import datetime as dt
import pytest
from docx import Document
from app.extensions import db
from app.files import stored_path
from app.models import Child, HistoricalReport, ROLE_ADMIN
from app.services import latest_previous_report
from conftest import login

# All names and text below are fictional.


@pytest.fixture(autouse=True)
def private_upload_folder(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)


def make_docx(text):
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def add_child(user, first="Asha", last="Testperson"):
    child = Child(first_name=first, last_name=last, current_education="Class 5",
                  created_by_id=user.id)
    db.session.add(child)
    db.session.commit()
    return child


def add_record(user, child, year, file_type="docx", name=None):
    """A database row only (no real file) for testing the 'previous report' lookup."""
    n = name or f"{child.id}-{year}-{file_type}"
    rec = HistoricalReport(child_id=child.id, reporting_year=year,
                           original_filename=f"{n}.{file_type}",
                           stored_name=f"{abs(hash(n)):032x}"[:32] + "." + file_type,
                           file_type=file_type, file_size=10, uploaded_by_id=user.id)
    db.session.add(rec)
    db.session.commit()
    return rec


def upload(client, child_id, filename, data, year="2024"):
    return client.post(f"/children/{child_id}/history/upload",
                       data={"reporting_year": year, "file": (io.BytesIO(data), filename)},
                       content_type="multipart/form-data")


def test_docx_upload_is_stored_safely(client, make_user, app):
    staff = make_user("s@example.org")
    child = add_child(staff)
    login(client, "s@example.org")
    r = upload(client, child.id, "Asha_Report.docx", make_docx("Asha loves painting."))
    assert r.status_code == 302
    db.session.expire_all()
    rec = db.session.execute(db.select(HistoricalReport)).scalar_one()
    assert rec.child_id == child.id
    assert rec.original_filename == "Asha_Report.docx"
    assert "Asha loves painting." in rec.extracted_text
    assert rec.stored_name != "Asha_Report.docx"          # server-made name
    path = stored_path(rec.stored_name)
    assert os.path.exists(path)
    assert path.startswith(app.config["UPLOAD_FOLDER"])    # in the private folder


def test_uploads_need_login(client, make_user):
    staff = make_user("s@example.org")
    child = add_child(staff)
    assert client.get(f"/children/{child.id}/history").status_code == 302
    assert upload(client, child.id, "a.docx", make_docx("x")).status_code == 302
    db.session.expire_all()
    assert db.session.execute(db.select(HistoricalReport)).first() is None


def test_wrong_extension_is_rejected(client, make_user):
    staff = make_user("s@example.org")
    child = add_child(staff)
    login(client, "s@example.org")
    r = upload(client, child.id, "virus.exe", b"MZ....")
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.execute(db.select(HistoricalReport)).first() is None


def test_fake_docx_is_rejected(client, make_user):
    staff = make_user("s@example.org")
    child = add_child(staff)
    login(client, "s@example.org")
    r = upload(client, child.id, "notes.docx", b"just some plain text, not a Word file")
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.execute(db.select(HistoricalReport)).first() is None


def test_fake_pdf_rejected_and_real_pdf_accepted(client, make_user):
    staff = make_user("s@example.org")
    child = add_child(staff)
    login(client, "s@example.org")
    assert upload(client, child.id, "a.pdf", b"not a pdf").status_code == 200
    assert upload(client, child.id, "a.pdf", b"%PDF-1.4\n%fictional test file\n").status_code == 302
    db.session.expire_all()
    assert db.session.execute(db.select(HistoricalReport)).scalar_one().file_type == "pdf"


def test_too_large_file_is_refused(client, make_user, app):
    staff = make_user("s@example.org")
    child = add_child(staff)
    login(client, "s@example.org")
    app.config["MAX_CONTENT_LENGTH"] = 2000
    r = upload(client, child.id, "big.docx", make_docx("x" * 5000) + b"0" * 5000)
    assert r.status_code == 413
    db.session.expire_all()
    assert db.session.execute(db.select(HistoricalReport)).first() is None


def test_download_gives_exact_original_and_needs_login(client, make_user):
    staff = make_user("s@example.org")
    child = add_child(staff)
    login(client, "s@example.org")
    original = make_docx("Original wording stays unchanged.")
    upload(client, child.id, "Asha_Report.docx", original)
    db.session.expire_all()
    rec = db.session.execute(db.select(HistoricalReport)).scalar_one()

    r = client.get(f"/history/{rec.id}/download")
    assert r.status_code == 200
    assert r.data == original
    assert "attachment" in r.headers["Content-Disposition"]

    client.post("/logout")
    assert client.get(f"/history/{rec.id}/download").status_code == 302


def test_latest_previous_report_is_for_the_right_child_and_year(make_user):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    bimal = add_child(staff, "Bimal", "Sampleman")
    add_record(staff, asha, 2022)
    r23 = add_record(staff, asha, 2023)
    add_record(staff, bimal, 2024)
    assert latest_previous_report(asha.id, 2025).id == r23.id
    assert latest_previous_report(asha.id, 2023).reporting_year == 2022
    assert latest_previous_report(asha.id, 2022) is None
    assert latest_previous_report(bimal.id, 2024) is None   # Asha's reports never leak to Bimal
    assert latest_previous_report(bimal.id, 2025).child_id == bimal.id


def test_word_file_preferred_over_pdf_for_same_year(make_user):
    staff = make_user("s@example.org")
    asha = add_child(staff)
    add_record(staff, asha, 2023, "pdf")
    docx = add_record(staff, asha, 2023, "docx")
    assert latest_previous_report(asha.id, 2024).id == docx.id


def test_history_list_shows_only_this_childs_reports(client, make_user):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    bimal = add_child(staff, "Bimal", "Sampleman")
    add_record(staff, asha, 2023, name="asha-report")
    add_record(staff, bimal, 2023, name="bimal-report")
    login(client, "s@example.org")
    page = client.get(f"/children/{asha.id}/history").data
    assert b"asha-report" in page and b"bimal-report" not in page


def test_only_admin_can_hide_and_file_is_kept(client, make_user):
    staff = make_user("s@example.org")
    make_user("boss@example.org", role=ROLE_ADMIN)
    child = add_child(staff)
    login(client, "s@example.org")
    upload(client, child.id, "a.docx", make_docx("Keep me."))
    db.session.expire_all()
    rec = db.session.execute(db.select(HistoricalReport)).scalar_one()
    assert client.post(f"/history/{rec.id}/remove").status_code == 403
    client.post("/logout")

    login(client, "boss@example.org")
    assert client.post(f"/history/{rec.id}/remove").status_code == 302
    db.session.expire_all()
    rec = db.session.get(HistoricalReport, rec.id)
    assert rec.is_removed is True
    assert os.path.exists(stored_path(rec.stored_name))      # original file preserved
    assert client.get(f"/history/{rec.id}/download").status_code == 404
    assert latest_previous_report(child.id, 2030) is None


def test_stored_path_refuses_unsafe_names():
    for bad in ["../secret.docx", "..\\x.docx", "report.docx", "a" * 32 + ".exe", ""]:
        with pytest.raises(ValueError):
            stored_path(bad)
