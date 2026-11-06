"""The contributions page. Names and notes are fictional."""
import datetime as dt
import pytest
from app.contributions.stats import contribution_table
from app.extensions import db
from app.models import (Category, Child, Clarification, GeneratedReport, HistoricalReport, Observation,
                        ReportApproval, ReportExport, ReportTemplate, ReportVersion, ROLE_ADMIN)
from conftest import login

UTC = dt.timezone.utc
TODAY = dt.date(2026, 11, 20)


@pytest.fixture
def people(app,make_user):
    alice = make_user("alice@example.org")
    bimal = make_user("bimal@example.org")
    boss = make_user("boss@example.org", role=ROLE_ADMIN)
    alice.name, bimal.name, boss.name = "Alice Writer", "Bimal Helper", "Boss Admin"
    db.session.commit()
    child = Child(first_name="Asha", last_name="T", current_education="Class 6", created_by_id=alice.id)
    cat = Category(name="Education", sort_order=1)
    template = ReportTemplate(version_number=1, is_active=True, prompt_text="TEST")
    db.session.add_all([child, cat, template])
    db.session.commit()
    return dict(alice=alice, bimal=bimal, boss=boss, child=child, cat=cat, template=template)


def note(p, user, when, text="a note", deleted=False):
    o = Observation(child_id=p["child"].id, category_id=p["cat"].id, event_date=when.date(), text=text,
                    created_by_id=user.id, created_at=when, is_deleted=deleted)
    db.session.add(o)
    db.session.commit()
    return o


def row_for(table, user):
    return next((r for r in table["rows"] if r["user"].id == user.id), None)


def test_counts_and_percentages_for_a_month(people):
    for day in (2, 3, 4):
        note(people, people["alice"], dt.datetime(2026, 11, day, 6, 0, tzinfo=UTC))
    note(people, people["bimal"], dt.datetime(2026, 11, 9, 6, 0, tzinfo=UTC))
    for day in range(1, 6):                                                  # October work is not November's
        note(people, people["alice"], dt.datetime(2026, 10, day + 5, 6, 0, tzinfo=UTC))
    table = contribution_table("month", dt.date(2026, 11, 15), TODAY)
    alice, bimal = row_for(table, people["alice"]), row_for(table, people["bimal"])
    assert (alice["total"], bimal["total"], table["team_total"]) == (3, 1, 4)
    assert (alice["percent"], bimal["percent"]) == (75.0, 25.0)
    assert [r["user"].name for r in table["rows"]][:2] == ["Alice Writer", "Bimal Helper"]
    assert table["label"] == "November 2026"


def test_the_day_changes_at_midnight_in_nepal(people):
    just_after = dt.datetime(2026, 10, 31, 19, 0, tzinfo=UTC)     # 00:45 on 1 November in Nepal
    just_before = dt.datetime(2026, 10, 31, 18, 0, tzinfo=UTC)    # 23:45 on 31 October in Nepal
    note(people, people["alice"], just_after)
    note(people, people["bimal"], just_before)
    november = contribution_table("month", dt.date(2026, 11, 15), TODAY)
    october = contribution_table("month", dt.date(2026, 10, 15), TODAY)
    assert row_for(november, people["alice"])["total"] == 1 and row_for(november, people["bimal"])["total"] == 0
    assert row_for(october, people["bimal"])["total"] == 1 and row_for(october, people["alice"])["total"] == 0


def test_week_and_year_views(people):
    note(people, people["alice"], dt.datetime(2026, 11, 2, 6, 0, tzinfo=UTC))    # Monday of 1-7 Nov
    note(people, people["alice"], dt.datetime(2026, 11, 10, 6, 0, tzinfo=UTC))   # next week
    note(people, people["alice"], dt.datetime(2026, 2, 10, 6, 0, tzinfo=UTC))
    assert row_for(contribution_table("week", dt.date(2026, 11, 5), TODAY), people["alice"])["total"] == 1
    assert row_for(contribution_table("year", dt.date(2026, 6, 1), TODAY), people["alice"])["total"] == 3
    assert row_for(contribution_table("year", dt.date(2025, 6, 1), TODAY), people["alice"])["total"] == 0


def test_every_kind_of_work_is_counted_once_for_the_right_person(people):
    when = dt.datetime(2026, 11, 5, 6, 0, tzinfo=UTC)
    alice, bimal, boss, child, template = (people[k] for k in ("alice", "bimal", "boss", "child", "template"))
    db.session.add(HistoricalReport(child_id=child.id, reporting_year=2025, original_filename="a.docx",
                                    stored_name="a" * 32 + ".docx", file_type="docx", file_size=1,
                                    uploaded_by_id=alice.id, uploaded_at=when))
    report = GeneratedReport(child_id=child.id, reporting_year=2026, template_id=template.id,
                             included_observation_ids="[]", status="approved", created_by_id=alice.id, created_at=when)
    db.session.add(report)
    db.session.flush()
    ai_draft = ReportVersion(generated_report_id=report.id, version_no=1, kind="ai_draft", body_text="x",
                             created_by_id=alice.id, created_at=when)
    edited = ReportVersion(generated_report_id=report.id, version_no=2, kind="edited", body_text="y",
                           created_by_id=bimal.id, created_at=when)
    db.session.add_all([ai_draft, edited])
    db.session.flush()
    db.session.add_all([
        Clarification(generated_report_id=report.id, round_no=1, question="Q?", answer="A", answered_by_id=bimal.id, answered_at=when),
        ReportExport(generated_report_id=report.id, version_id=edited.id, filename="Asha_Report.docx",
                     stored_name="b" * 32 + ".docx", page_check="ok", created_by_id=bimal.id, created_at=when),
        ReportApproval(generated_report_id=report.id, version_id=edited.id, approved_by_id=boss.id, approved_at=when)])
    db.session.commit()

    table = contribution_table("month", dt.date(2026, 11, 15), TODAY)
    a, b, c = row_for(table, alice), row_for(table, bimal), row_for(table, boss)
    assert a["counts"]["history_uploaded"] == 1 and a["counts"]["reports_started"] == 1
    assert a["counts"]["text_edits"] == 0                       # the AI draft is not a person's edit
    assert b["counts"]["text_edits"] == 1 and b["counts"]["questions_answered"] == 1 and b["counts"]["exports"] == 1
    assert c["counts"]["approvals"] == 1
    assert (a["total"], b["total"], c["total"]) == (2, 3, 1)


def test_removed_notes_and_idle_inactive_people_do_not_count(people):
    when = dt.datetime(2026, 11, 5, 6, 0, tzinfo=UTC)
    note(people, people["alice"], when)
    note(people, people["alice"], when, deleted=True)
    people["bimal"].is_active = False
    db.session.commit()
    table = contribution_table("month", dt.date(2026, 11, 15), TODAY)
    assert row_for(table, people["alice"])["total"] == 1
    assert row_for(table, people["bimal"]) is None                 # inactive and nothing done
    note(people, people["bimal"], when)
    assert row_for(contribution_table("month", dt.date(2026, 11, 15), TODAY), people["bimal"])["total"] == 1


def test_an_empty_period_has_no_division_by_zero(people):
    table = contribution_table("month", dt.date(2020, 1, 15), TODAY)
    assert table["team_total"] == 0 and all(r["percent"] == 0.0 for r in table["rows"])


def test_admin_sees_everyone_and_staff_see_only_themselves(client, people):
    now = dt.datetime.now(UTC)
    for _ in range(3):
        note(people, people["alice"], now)
    note(people, people["bimal"], now)

    login(client, "boss@example.org")
    page = client.get("/contributions/?view=year").data
    assert b"Alice Writer" in page and b"Bimal Helper" in page and b"75.0%" in page and b"25.0%" in page
    client.post("/logout")

    login(client, "alice@example.org")
    page = client.get("/contributions/?view=year").data
    assert b"Alice Writer" in page and b"Bimal Helper" not in page and b"75.0%" in page


def test_the_page_copes_with_strange_input_and_needs_login(client, people):
    assert client.get("/contributions/").status_code == 302
    login(client, "boss@example.org")
    for url in ["/contributions/?view=bogus", "/contributions/?date=garbage", "/contributions/?date=2099-01-01",
                "/contributions/?view=week", "/contributions/?view=year&date=2020-05-05"]:
        assert client.get(url).status_code == 200, url
