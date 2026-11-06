"""Editing, AI length revision, Word export and approval. The AI is always a fake.
All children and text are fictional."""
import datetime as dt
import io
import json
import os
import pytest
from docx import Document
from app.ai.base import AIError, AIResult
from app.extensions import db
from app.models import (Child, GeneratedReport, ReportApproval, ReportExport, ReportTemplate,
                        ReportVersion, ROLE_ADMIN)
from conftest import login


class FakeProvider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, system_prompt, user_message):
        self.calls.append((system_prompt, user_message))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return AIResult(text=reply, model="fake-model")


@pytest.fixture(autouse=True)
def private_upload_folder(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)


@pytest.fixture
def use_ai(monkeypatch):
    def _use(*replies):
        provider = FakeProvider(*replies)
        monkeypatch.setattr("app.ai.get_provider", lambda: provider)
        return provider
    return _use


@pytest.fixture
def estimate_only(monkeypatch):
    """Make the page check predictable: pretend no page renderer is installed."""
    monkeypatch.setattr("app.pagecheck.find_soffice", lambda: None)


def report_text(first="Asha", education="Class 6", words=490):
    paragraphs, n = [], 0
    while n < words:
        k = min(85, words - n)
        paragraphs.append(" ".join(["word"] * k))
        n += k
    return f"Name: {first}\nClass/Education: {education}\n\n" + "\n\n".join(paragraphs)


def reply_report(**kw):
    return json.dumps({"status": "report", "report": report_text(**kw), "notes_outside_report": ""})


@pytest.fixture
def rw(app, make_user):
    staff = make_user("s@example.org")
    admin = make_user("boss@example.org", role=ROLE_ADMIN)
    asha = Child(first_name="Asha", last_name="Testperson", current_education="Class 6", created_by_id=staff.id)
    template = ReportTemplate(version_number=1, is_active=True, prompt_text="TEST INSTRUCTIONS")
    db.session.add_all([asha, template])
    db.session.flush()
    report = GeneratedReport(child_id=asha.id, reporting_year=2025, template_id=template.id,
                             included_observation_ids="[]", extra_bullets="- Asha won the school quiz.",
                             previous_report_confirmed_missing=True, status="draft_ready",
                             created_by_id=staff.id)
    db.session.add(report)
    db.session.flush()
    v1 = ReportVersion(generated_report_id=report.id, version_no=1, kind="ai_draft",
                       body_text=report_text(), created_by_id=staff.id)
    db.session.add(v1)
    db.session.commit()
    return type("RW", (), dict(staff=staff, admin=admin, asha=asha, template=template,
                               report=report, v1=v1))


def versions(report):
    db.session.expire_all()
    return db.session.execute(
        db.select(ReportVersion).where(ReportVersion.generated_report_id == report.id)
        .order_by(ReportVersion.version_no)).scalars().all()


def as_staff(client):
    login(client, "s@example.org")


def as_admin(client):
    login(client, "boss@example.org")


def save(client, rw, text, base="1"):
    return client.post(f"/reports/{rw.report.id}/save", data={"text": text, "base_version": base})


# ---------- editing and versions ----------
def test_an_edit_makes_a_new_version_and_keeps_the_ai_draft(client, rw):
    as_staff(client)
    edited = report_text(words=495).replace("word", "term", 3)
    assert save(client, rw, edited).status_code == 302
    v = versions(rw.report)
    assert [(x.version_no, x.kind) for x in v] == [(1, "ai_draft"), (2, "edited")]
    assert v[0].body_text == report_text()          # original AI draft untouched
    assert v[1].body_text == edited.strip() and v[1].created_by_id == rw.staff.id


def test_saving_unchanged_text_makes_no_new_version(client, rw):
    as_staff(client)
    save(client, rw, report_text())
    assert len(versions(rw.report)) == 1


def test_a_stale_editor_is_refused_and_keeps_the_typed_text(client, rw):
    as_staff(client)
    save(client, rw, report_text(words=491))                       # version 2
    r = save(client, rw, "Name: Asha\nClass/Education: Class 6\n\nMy slower edit", base="1")
    assert r.status_code == 200 and b"My slower edit" in r.data and b"newer version" in r.data
    assert len(versions(rw.report)) == 2


def test_empty_text_is_refused(client, rw):
    as_staff(client)
    assert save(client, rw, "   ").status_code == 200
    assert len(versions(rw.report)) == 1


def test_an_old_version_can_be_viewed_and_used_again(client, rw):
    as_staff(client)
    save(client, rw, report_text(words=495))
    assert b"word" in client.get(f"/reports/{rw.report.id}/versions/{rw.v1.id}").data
    assert client.post(f"/reports/{rw.report.id}/restore/{rw.v1.id}").status_code == 302
    v = versions(rw.report)
    assert len(v) == 3 and v[2].body_text == v[0].body_text and v[2].kind == "edited"


def test_a_version_of_another_report_is_not_reachable(client, rw):
    other = GeneratedReport(child_id=rw.asha.id, reporting_year=2024, template_id=rw.template.id,
                            included_observation_ids="[]", status="draft_ready", created_by_id=rw.staff.id)
    db.session.add(other)
    db.session.commit()
    as_staff(client)
    assert client.get(f"/reports/{other.id}/versions/{rw.v1.id}").status_code == 404
    assert client.post(f"/reports/{other.id}/restore/{rw.v1.id}").status_code == 404


# ---------- AI length revision ----------
def test_ai_revision_is_saved_as_a_new_version(client, rw, use_ai):
    provider = use_ai(reply_report(words=488))
    as_staff(client)
    short = report_text(words=300)
    save(client, rw, short)
    assert client.post(f"/reports/{rw.report.id}/revise").status_code == 302
    v = versions(rw.report)
    assert [x.kind for x in v] == ["ai_draft", "edited", "ai_revision"]
    assert v[1].body_text == short.strip()                          # the staff edit is kept
    system, user = provider.calls[0]
    assert "<revision_request>" in user and "has 300 words" in user
    assert db.session.get(GeneratedReport, rw.report.id).status == "draft_ready"


def test_a_failed_revision_leaves_the_draft_usable(client, rw, use_ai):
    use_ai(AIError("The AI took too long to answer. Please try again in a minute.", "timeout"))
    as_staff(client)
    client.post(f"/reports/{rw.report.id}/revise")
    db.session.expire_all()
    assert db.session.get(GeneratedReport, rw.report.id).status == "draft_ready"
    assert len(versions(rw.report)) == 1


def test_a_revision_cannot_start_while_one_is_running(client, rw, use_ai):
    provider = use_ai(reply_report())
    rw.report.status = "generating"
    db.session.commit()
    as_staff(client)
    assert client.post(f"/reports/{rw.report.id}/revise").status_code == 302
    assert provider.calls == []


# ---------- Word export ----------
def test_export_creates_a_private_word_file(client, rw, app, estimate_only):
    as_staff(client)
    assert client.post(f"/reports/{rw.report.id}/export").status_code == 302
    db.session.expire_all()
    exp = db.session.execute(db.select(ReportExport)).scalar_one()
    assert exp.filename == "Asha_Report.docx" and exp.version_id == rw.v1.id
    assert exp.page_check == "estimated_ok"
    path = os.path.join(app.config["UPLOAD_FOLDER"], "generated", exp.stored_name)
    assert os.path.exists(path) and exp.stored_name != exp.filename

    r = client.get(f"/exports/{exp.id}/download")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    doc = Document(io.BytesIO(r.data))
    assert doc.paragraphs[0].text == "Name: Asha"
    assert doc.paragraphs[1].text == "Class/Education: Class 6"


def test_filename_gets_initials_only_when_first_names_collide(client, rw, estimate_only):
    db.session.add(Child(first_name="asha", last_name="Rai", current_education="Class 3",
                         created_by_id=rw.staff.id))
    db.session.commit()
    as_staff(client)
    client.post(f"/reports/{rw.report.id}/export")
    db.session.expire_all()
    assert db.session.execute(db.select(ReportExport)).scalar_one().filename == "Asha_T_Report.docx"


def test_export_is_refused_when_the_identification_lines_are_wrong(client, rw, estimate_only):
    as_staff(client)
    save(client, rw, "Hello there.\n\n" + report_text(words=490))
    client.post(f"/reports/{rw.report.id}/export")
    db.session.expire_all()
    assert db.session.execute(db.select(ReportExport)).first() is None


def test_downloads_need_login(client, rw, estimate_only):
    as_staff(client)
    client.post(f"/reports/{rw.report.id}/export")
    db.session.expire_all()
    exp = db.session.execute(db.select(ReportExport)).scalar_one()
    client.post("/logout")
    assert client.get(f"/exports/{exp.id}/download").status_code == 302


# ---------- approval ----------
def test_only_an_administrator_can_approve(client, rw):
    as_staff(client)
    assert client.post(f"/reports/{rw.report.id}/approve", data={"confirm_read": "1", "confirm_warnings": "1"}).status_code == 403


def test_approval_needs_the_read_confirmation_and_accepted_warnings(client, rw, estimate_only):
    as_admin(client)
    url = f"/reports/{rw.report.id}/approve"
    client.post(url, data={})                                  # nothing ticked
    client.post(url, data={"confirm_read": "1"})              # not exported yet = a warning
    db.session.expire_all()
    assert db.session.get(GeneratedReport, rw.report.id).status == "draft_ready"
    assert db.session.execute(db.select(ReportApproval)).first() is None

    client.post(url, data={"confirm_read": "1", "confirm_warnings": "1"})
    db.session.expire_all()
    assert db.session.get(GeneratedReport, rw.report.id).status == "approved"
    approval = db.session.execute(db.select(ReportApproval)).scalar_one()
    assert approval.version_id == rw.v1.id and approval.approved_by_id == rw.admin.id
    assert approval.accepted_warnings is True


def test_clean_report_needs_only_the_read_confirmation(client, rw, estimate_only):
    as_admin(client)
    client.post(f"/reports/{rw.report.id}/export")
    client.post(f"/reports/{rw.report.id}/approve", data={"confirm_read": "1"})
    db.session.expire_all()
    assert db.session.get(GeneratedReport, rw.report.id).status == "approved"
    assert db.session.execute(db.select(ReportApproval)).scalar_one().accepted_warnings is False


def test_a_page_overflow_is_flagged_for_human_review(client, rw, monkeypatch):
    monkeypatch.setattr("app.reports.routes.check_pages", lambda *a: {
        "count": 2, "status": "too_long", "note": "Rendered with LibreOffice: 2 pages."})
    as_admin(client)
    client.post(f"/reports/{rw.report.id}/export")
    client.post(f"/reports/{rw.report.id}/approve", data={"confirm_read": "1"})
    db.session.expire_all()
    assert db.session.get(GeneratedReport, rw.report.id).status == "draft_ready"
    assert b"2 pages" in client.get(f"/reports/{rw.report.id}").data


def test_an_approved_report_is_locked_until_an_administrator_reopens_it(client, rw, estimate_only):
    as_admin(client)
    client.post(f"/reports/{rw.report.id}/export")
    client.post(f"/reports/{rw.report.id}/approve", data={"confirm_read": "1"})
    save(client, rw, report_text(words=492))
    assert len(versions(rw.report)) == 1                       # edit refused while approved
    client.post("/logout")

    as_staff(client)
    assert client.post(f"/reports/{rw.report.id}/reopen").status_code == 403
    client.post("/logout")

    as_admin(client)
    client.post(f"/reports/{rw.report.id}/reopen")
    save(client, rw, report_text(words=492))
    db.session.expire_all()
    assert db.session.get(GeneratedReport, rw.report.id).status == "draft_ready"
    assert len(versions(rw.report)) == 2
    assert len(db.session.execute(db.select(ReportApproval)).scalars().all()) == 1   # history kept
