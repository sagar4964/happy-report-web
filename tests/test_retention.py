"""Permanent deletion of one child. All data is fictional."""
import os
import pytest
from app.extensions import db
from app.files import save_bytes, save_generated, stored_path, generated_path
from app.models import (AuditEvent, Category, Child, Clarification, GeneratedReport, HistoricalReport,
                        Observation, ReportApproval, ReportExport, ReportTemplate, ReportVersion)
import datetime as dt


@pytest.fixture(autouse=True)
def private_upload_folder(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)


def build_child(user, template, cat, first, last):
    child = Child(first_name=first, last_name=last, current_education="Class 6", created_by_id=user.id)
    db.session.add(child)
    db.session.flush()
    db.session.add(Observation(child_id=child.id, category_id=cat.id, event_date=dt.date(2025, 3, 1),
                               text=f"{first} won the quiz.", created_by_id=user.id))
    hist = HistoricalReport(child_id=child.id, reporting_year=2024, original_filename=f"{first}.docx",
                            stored_name=save_bytes(b"old report " + first.encode(), "docx"),
                            file_type="docx", file_size=10, extracted_text="old", uploaded_by_id=user.id)
    report = GeneratedReport(child_id=child.id, reporting_year=2025, template_id=template.id,
                             included_observation_ids="[]", status="approved", created_by_id=user.id)
    db.session.add_all([hist, report])
    db.session.flush()
    version = ReportVersion(generated_report_id=report.id, version_no=1, kind="ai_draft",
                            body_text="Name: x", created_by_id=user.id)
    db.session.add(version)
    db.session.flush()
    export = ReportExport(generated_report_id=report.id, version_id=version.id,
                          filename=f"{first}_Report.docx", stored_name=save_generated(b"docx " + first.encode()),
                          page_check="ok", created_by_id=user.id)
    db.session.add_all([
        export,
        ReportApproval(generated_report_id=report.id, version_id=version.id, approved_by_id=user.id),
        Clarification(generated_report_id=report.id, round_no=1, question="Which class?", answer="Class 6")])
    db.session.commit()
    return child, hist, export


@pytest.fixture
def two_children(app, make_user):
    staff = make_user("s@example.org")
    template = ReportTemplate(version_number=1, is_active=True, prompt_text="TEST")
    cat = Category(name="Education", sort_order=1)
    db.session.add_all([template, cat])
    db.session.commit()
    a = build_child(staff, template, cat, "Asha", "Testperson")
    b = build_child(staff, template, cat, "Bimal", "Sampleman")
    return a, b


def count(model, **filters):
    db.session.expire_all()
    return len(db.session.execute(db.select(model).filter_by(**filters)).scalars().all())


def test_deleting_a_child_removes_all_their_data_and_files_but_nobody_elses(app, two_children):
    (asha, a_hist, a_exp), (bimal, b_hist, b_exp) = two_children
    a_files = [stored_path(a_hist.stored_name), generated_path(a_exp.stored_name)]
    b_files = [stored_path(b_hist.stored_name), generated_path(b_exp.stored_name)]
    asha_id, bimal_id = asha.id, bimal.id
    assert all(os.path.exists(p) for p in a_files + b_files)

    result = app.test_cli_runner().invoke(args=["delete-child", str(asha_id)], input="asha testperson\n")
    assert result.exit_code == 0, result.output

    assert count(Child, id=asha_id) == 0
    assert count(Observation, child_id=asha_id) == 0
    assert count(HistoricalReport, child_id=asha_id) == 0
    assert count(GeneratedReport, child_id=asha_id) == 0
    assert count(ReportExport) == 1 and count(ReportApproval) == 1
    assert count(ReportVersion) == 1 and count(Clarification) == 1
    assert not any(os.path.exists(p) for p in a_files)

    assert count(Child, id=bimal_id) == 1 and count(Observation, child_id=bimal_id) == 1
    assert all(os.path.exists(p) for p in b_files)

    audit = db.session.execute(db.select(AuditEvent).filter_by(action="child_deleted_permanently")).scalar_one()
    assert audit.entity_id == asha_id and "Asha" not in (audit.detail or "")


def test_the_wrong_name_deletes_nothing(app, two_children):
    (asha, _h, _e), _b = two_children
    result = app.test_cli_runner().invoke(args=["delete-child", str(asha.id)], input="Somebody Else\n")
    assert result.exit_code != 0
    assert count(Child) == 2 and count(Observation) == 2


def test_an_unknown_id_is_explained(app, two_children):
    result = app.test_cli_runner().invoke(args=["delete-child", "9999"])
    assert result.exit_code != 0 and "No child" in result.output
    assert count(Child) == 2
