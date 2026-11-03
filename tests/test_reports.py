"""Report generation tests. The AI is always replaced by a fake: no internet, no cost.
All children, notes and reports below are fictional."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from app.ai.base import AIError, AIResult
from app.extensions import db
from app.models import (Category, Child, Clarification, GeneratedReport, HistoricalReport,
                        Observation, ReportingPeriod, ReportTemplate, ReportVersion,
                        ROLE_ADMIN, utcnow)
from conftest import login

PROMPT_FILE = Path(__file__).resolve().parents[1] / "app" / "prompts" / "report_prompt_v1.txt"
PROMPT_SHA256 = "b4798662893cc247fb5ea41df9b3c9ad44ed1351a520aac5cb9ad707f804b28c"


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


@pytest.fixture
def use_ai(monkeypatch):
    def _use(*replies):
        provider = FakeProvider(*replies)
        monkeypatch.setattr("app.ai.get_provider", lambda: provider)
        return provider
    return _use


def report_text(first="Asha", education="Class 6", words=490):
    return f"Name: {first}\nClass/Education: {education}\n\n" + " ".join(["word"] * words)


def reply_report(**kw):
    return json.dumps({"status": "report", "report": report_text(**kw), "notes_outside_report": ""})


def reply_questions(*questions):
    return json.dumps({"status": "questions", "questions": list(questions)})


@pytest.fixture
def world(app, make_user):
    staff = make_user("s@example.org")
    asha = Child(first_name="Asha", last_name="Testperson", current_education="Class 6", created_by_id=staff.id)
    bimal = Child(first_name="Bimal", last_name="Sampleman", current_education="Class 8", created_by_id=staff.id)
    cat = Category(name="Education and examinations", sort_order=1)
    period = ReportingPeriod(year=2025, start_date=dt.date(2025, 1, 1), end_date=dt.date(2025, 12, 31))
    template = ReportTemplate(version_number=1, is_active=True, prompt_text="TEST INSTRUCTIONS: write well.")
    db.session.add_all([asha, bimal, cat, period, template])
    db.session.flush()
    a_obs = Observation(child_id=asha.id, category_id=cat.id, event_date=dt.date(2025, 3, 1),
                        text="Asha won the school quiz.", created_by_id=staff.id)
    b_obs = Observation(child_id=bimal.id, category_id=cat.id, event_date=dt.date(2025, 4, 1),
                        text="Bimal broke his arm falling from a tree.", created_by_id=staff.id)

    def prev(child, letter, text, file_type="docx"):
        return HistoricalReport(child_id=child.id, reporting_year=2024,
                                original_filename=f"{child.first_name}24.{file_type}",
                                stored_name=letter * 32 + "." + file_type, file_type=file_type,
                                file_size=10, extracted_text=text, uploaded_by_id=staff.id)
    a_prev = prev(asha, "a", "Asha loved painting last time.")
    b_prev = prev(bimal, "b", "Bimal liked football in the old report.")
    a_pdf = prev(asha, "c", None, "pdf")
    db.session.add_all([a_obs, b_obs, a_prev, b_prev, a_pdf])
    db.session.commit()
    return NS(staff=staff, asha=asha, bimal=bimal, cat=cat, period=period, template=template,
              a_obs=a_obs, b_obs=b_obs, a_prev=a_prev, b_prev=b_prev, a_pdf=a_pdf)


def submit(client, w, child=None, **over):
    child = child or w.asha
    data = {"period": str(w.period.id), "confirm_identity": "1", "obs_ids": [str(w.a_obs.id)],
            "previous_report_id": str(w.a_prev.id), "receipt_context": "January 2027"}
    data.update(over)
    data = {k: v for k, v in data.items() if v is not None}
    return client.post(f"/children/{child.id}/reports/new", data=data)


def all_reports():
    db.session.expire_all()
    return db.session.execute(db.select(GeneratedReport)).scalars().all()


# ---------- access ----------
def test_report_pages_need_login(client, world):
    assert client.get("/reports/").status_code == 302
    assert client.get(f"/children/{world.asha.id}/reports/new").status_code == 302
    assert client.get("/instructions/").status_code == 302


def test_prepare_page_shows_identity_and_only_this_childs_notes(client, world):
    login(client, "s@example.org")
    page = client.get(f"/children/{world.asha.id}/reports/new").data
    assert b"Asha Testperson" in page and b"Class 6" in page
    assert b"Asha won the school quiz." in page and b"Asha loved painting" not in page
    assert b"Bimal" not in page


# ---------- successful generation ----------
def test_successful_generation_saves_draft_and_sends_only_this_childs_data(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world).status_code == 302
    rep = all_reports()[0]
    assert rep.status == "draft_ready"
    assert rep.child_id == world.asha.id and rep.template_id == world.template.id
    ver = db.session.execute(db.select(ReportVersion)).scalar_one()
    assert ver.kind == "ai_draft" and ver.version_no == 1

    assert len(provider.calls) == 1
    system, user = provider.calls[0]
    assert "TEST INSTRUCTIONS: write well." in system
    assert "Asha won the school quiz." in user and "Asha loved painting last time." in user
    for leak in ["Testperson", "Sampleman", "Bimal", "broke his arm", "football"]:
        assert leak not in user
    assert b"490 words" in client.get(f"/reports/{rep.id}").data
    listing = client.get("/reports/").data
    assert b"Draft ready" in listing and b"Asha Testperson" in listing


def test_pasted_bullets_alone_are_enough(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    r = submit(client, world, obs_ids=[], extra_bullets="- Asha learned to ride a bicycle")
    assert r.status_code == 302
    assert "learned to ride a bicycle" in provider.calls[0][1]


# ---------- clarification questions ----------
def test_questions_are_asked_together_answered_and_report_regenerated(client, world, use_ai):
    provider = use_ai(reply_questions("Did Asha pass the SEE?", "Which festival was meant?"), reply_report())
    login(client, "s@example.org")
    submit(client, world)
    rep = all_reports()[0]
    assert rep.status == "needs_answers"
    clars = db.session.execute(db.select(Clarification)).scalars().all()
    assert len(clars) == 2 and all(c.round_no == 1 and c.answer is None for c in clars)
    page = client.get(f"/reports/{rep.id}").data
    assert b"Did Asha pass the SEE?" in page and b"Which festival was meant?" in page

    # a blank answer is refused and nothing is sent to the AI
    blank = {f"answer_{clars[0].id}": "Yes, she passed", f"answer_{clars[1].id}": " "}
    assert client.post(f"/reports/{rep.id}/answers", data=blank).status_code == 200
    assert len(provider.calls) == 1

    good = {f"answer_{c.id}": f"Confirmed fact {c.id}" for c in clars}
    assert client.post(f"/reports/{rep.id}/answers", data=good).status_code == 302
    assert all_reports()[0].status == "draft_ready"
    user = provider.calls[1][1]
    assert "Question: Did Asha pass the SEE?" in user and f"Answer: Confirmed fact {clars[0].id}" in user
    assert "<clarification_round>1</clarification_round>" in user


# ---------- failures ----------
def test_ai_failure_keeps_inputs_and_retry_works(client, world, use_ai):
    provider = use_ai(AIError("The AI took too long to answer. Please try again in a minute.", "timeout"),
                      reply_report())
    login(client, "s@example.org")
    submit(client, world)
    rep = all_reports()[0]
    assert rep.status == "failed" and "too long" in rep.last_error
    assert json.loads(rep.included_observation_ids) == [world.a_obs.id]
    assert b"too long" in client.get(f"/reports/{rep.id}").data

    assert client.post(f"/reports/{rep.id}/retry").status_code == 302
    assert all_reports()[0].status == "draft_ready"
    assert len(provider.calls) == 2


def test_unreadable_ai_reply_is_a_clean_failure(client, world, use_ai):
    use_ai("this is not json at all")
    login(client, "s@example.org")
    submit(client, world)
    rep = all_reports()[0]
    assert rep.status == "failed" and "could not be understood" in rep.last_error
    assert db.session.execute(db.select(ReportVersion)).first() is None


def test_unexpected_crash_in_provider_is_a_clean_failure(client, world, use_ai):
    use_ai(RuntimeError("boom with secret details"))
    login(client, "s@example.org")
    submit(client, world)
    rep = all_reports()[0]
    assert rep.status == "failed" and "secret details" not in rep.last_error


def test_missing_ai_settings_are_explained(client, world, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    login(client, "s@example.org")
    submit(client, world)
    rep = all_reports()[0]
    assert rep.status == "failed" and "OPENAI_API_KEY" in rep.last_error


# ---------- double clicks ----------
def make_stuck_report(world, minutes_old):
    rep = GeneratedReport(child_id=world.asha.id, reporting_year=2025, template_id=world.template.id,
                          included_observation_ids=json.dumps([world.a_obs.id]),
                          status="generating", created_by_id=world.staff.id)
    db.session.add(rep)
    db.session.commit()
    old = utcnow() - dt.timedelta(minutes=minutes_old)
    rep.created_at = old
    rep.updated_at = old
    db.session.commit()
    return rep


def test_a_report_that_is_being_generated_cannot_be_started_again(client, world, use_ai):
    provider = use_ai(reply_report())
    rep = make_stuck_report(world, minutes_old=0)
    login(client, "s@example.org")
    assert client.post(f"/reports/{rep.id}/retry").status_code == 302
    assert provider.calls == []


def test_a_stuck_report_can_be_retried_after_a_few_minutes(client, world, use_ai):
    provider = use_ai(reply_report())
    rep = make_stuck_report(world, minutes_old=10)
    login(client, "s@example.org")
    client.post(f"/reports/{rep.id}/retry")
    assert len(provider.calls) == 1
    assert all_reports()[0].status == "draft_ready"


# ---------- safety checks on the form ----------
def test_identity_must_be_confirmed(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world, confirm_identity=None).status_code == 200
    assert all_reports() == [] and provider.calls == []


def test_another_childs_previous_report_is_refused(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world, previous_report_id=str(world.b_prev.id)).status_code == 200
    assert all_reports() == [] and provider.calls == []


def test_another_childs_observation_is_refused(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world, obs_ids=[str(world.b_obs.id)]).status_code == 200
    assert all_reports() == [] and provider.calls == []


def test_pdf_without_text_cannot_be_the_previous_report(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world, previous_report_id=str(world.a_pdf.id)).status_code == 200
    assert all_reports() == [] and provider.calls == []


def test_no_previous_report_needs_an_explicit_confirmation(client, world, use_ai):
    provider = use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world, previous_report_id="").status_code == 200
    assert all_reports() == []
    assert submit(client, world, previous_report_id="", confirm_no_previous="1").status_code == 302
    assert 'status="confirmed_by_staff_not_available"' in provider.calls[0][1]


def test_nothing_to_send_is_refused(client, world, use_ai):
    use_ai(reply_report())
    login(client, "s@example.org")
    assert submit(client, world, obs_ids=[], extra_bullets="").status_code == 200
    assert all_reports() == []


def test_no_active_instructions_blocks_generation(client, world, use_ai):
    provider = use_ai(reply_report())
    world.template.is_active = False
    db.session.commit()
    login(client, "s@example.org")
    assert submit(client, world).status_code == 200
    assert all_reports() == [] and provider.calls == []


# ---------- Report Writing Instructions ----------
def test_instruction_versions_are_kept_and_staff_cannot_change_them(client, world, make_user, use_ai):
    make_user("boss@example.org", role=ROLE_ADMIN)
    login(client, "s@example.org")
    assert client.get("/instructions/").status_code == 200
    assert client.get("/instructions/new").status_code == 403
    assert client.post("/instructions/new", data={"prompt_text": "x" * 300}).status_code == 403
    client.post("/logout")

    login(client, "boss@example.org")
    r = client.post("/instructions/new", data={"note": "Changed tone", "prompt_text": "NEW INSTRUCTIONS " + "x" * 300})
    assert r.status_code == 302
    db.session.expire_all()
    versions = db.session.execute(db.select(ReportTemplate).order_by(ReportTemplate.version_number)).scalars().all()
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].prompt_text == "TEST INSTRUCTIONS: write well." and not versions[0].is_active
    assert versions[1].is_active and versions[1].prompt_text.startswith("NEW INSTRUCTIONS")

    provider = use_ai(reply_report())
    submit(client, world)
    assert all_reports()[0].template_id == versions[1].id
    assert provider.calls[0][0].startswith("NEW INSTRUCTIONS")

    assert client.post(f"/instructions/{versions[0].id}/activate").status_code == 302
    db.session.expire_all()
    assert db.session.get(ReportTemplate, versions[0].id).is_active
    assert not db.session.get(ReportTemplate, versions[1].id).is_active


def test_saved_prompt_file_has_not_been_changed():
    text = PROMPT_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == PROMPT_SHA256
    assert "Target STRICTLY 480-500 words of report body text" in text
    assert "Always write 'Happy Children', never 'Happy Home'." in text
    assert text.startswith("### HAPPY CHILDREN NEPAL | ANNUAL SPONSOR REPORT WRITER")


def test_seed_defaults_saves_the_exact_prompt_as_version_one(app):
    result = app.test_cli_runner().invoke(args=["seed-defaults"])
    assert result.exit_code == 0
    db.session.expire_all()
    v1 = db.session.execute(db.select(ReportTemplate)).scalar_one()
    assert v1.version_number == 1 and v1.is_active
    assert v1.prompt_text == PROMPT_FILE.read_text(encoding="utf-8")
    again = app.test_cli_runner().invoke(args=["seed-defaults"])  # safe to repeat
    assert again.exit_code == 0
    db.session.expire_all()
    assert len(db.session.execute(db.select(ReportTemplate)).scalars().all()) == 1
