import datetime as dt
import pytest
from app.extensions import db
from app.models import (Child, Category, Observation, ReportingPeriod, ROLE_ADMIN)
from conftest import login

# All names and notes below are fictional.


@pytest.fixture
def base_data(app):
    cat = Category(name="Education and examinations", sort_order=1)
    p24 = ReportingPeriod(year=2024, start_date=dt.date(2024, 1, 1), end_date=dt.date(2024, 12, 31))
    p23 = ReportingPeriod(year=2023, start_date=dt.date(2023, 1, 1), end_date=dt.date(2023, 12, 31))
    db.session.add_all([cat, p24, p23])
    db.session.commit()
    return {"cat": cat, "p24": p24, "p23": p23}


def add_child(user, first, last, education="Class 5"):
    child = Child(first_name=first, last_name=last, current_education=education,
                  created_by_id=user.id)
    db.session.add(child)
    db.session.commit()
    return child


def add_obs(user, child, cat, text, date):
    obs = Observation(child_id=child.id, category_id=cat.id, text=text,
                      event_date=date, created_by_id=user.id)
    db.session.add(obs)
    db.session.commit()
    return obs


def obs_form(cat, text="She finished the maths test.", date="2024-03-05", **extra):
    data = {"event_date": date, "category_id": str(cat.id), "text": text}
    data.update(extra)
    return data


# ---------- children ----------
def test_children_pages_need_login(client):
    assert client.get("/children/").status_code == 302


def test_staff_can_create_child(client, make_user):
    staff = make_user("s@example.org")
    login(client, "s@example.org")
    r = client.post("/children/new", data={
        "first_name": "Asha", "last_name": "Testperson", "current_education": "Class 6"})
    assert r.status_code == 302
    db.session.expire_all()
    child = db.session.execute(db.select(Child)).scalar_one()
    assert child.full_name == "Asha Testperson"
    assert child.created_by_id == staff.id


def test_search_finds_by_name(client, make_user):
    staff = make_user("s@example.org")
    add_child(staff, "Asha", "Testperson")
    add_child(staff, "Bimal", "Sampleman")
    login(client, "s@example.org")
    r = client.get("/children/?q=asha")
    assert b"Asha Testperson" in r.data
    assert b"Bimal Sampleman" not in r.data


def test_same_name_needs_confirmation(client, make_user):
    staff = make_user("s@example.org")
    add_child(staff, "Asha", "Testperson")
    login(client, "s@example.org")
    data = {"first_name": "asha", "last_name": "TESTPERSON", "current_education": "Class 3"}
    r = client.post("/children/new", data=data)
    assert r.status_code == 200
    db.session.expire_all()
    assert len(db.session.execute(db.select(Child)).scalars().all()) == 1
    data["confirm_duplicate"] = "y"
    r = client.post("/children/new", data=data)
    assert r.status_code == 302
    db.session.expire_all()
    assert len(db.session.execute(db.select(Child)).scalars().all()) == 2


def test_only_admin_can_archive(client, make_user):
    staff = make_user("s@example.org")
    make_user("boss@example.org", role=ROLE_ADMIN)
    child = add_child(staff, "Asha", "Testperson")

    login(client, "s@example.org")
    assert client.post(f"/children/{child.id}/archive").status_code == 403
    client.post("/logout")

    login(client, "boss@example.org")
    assert client.post(f"/children/{child.id}/archive").status_code == 302
    db.session.expire_all()
    assert db.session.get(Child, child.id).is_active is False
    assert b"Asha Testperson" not in client.get("/children/").data
    assert b"Asha Testperson" in client.get("/children/?archived=1").data


# ---------- observations ----------
def test_observation_is_saved_for_the_right_child(client, make_user, base_data):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    bimal = add_child(staff, "Bimal", "Sampleman")
    login(client, "s@example.org")
    r = client.post(f"/children/{asha.id}/observations/new", data=obs_form(base_data["cat"]))
    assert r.status_code == 302
    db.session.expire_all()
    obs = db.session.execute(db.select(Observation)).scalar_one()
    assert obs.child_id == asha.id
    assert b"maths test" not in client.get(f"/children/{bimal.id}?period=all").data
    assert b"maths test" in client.get(f"/children/{asha.id}?period=all").data


def test_other_childs_observations_are_not_shown(client, make_user, base_data):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    bimal = add_child(staff, "Bimal", "Sampleman")
    add_obs(staff, bimal, base_data["cat"], "Bimal won the quiz.", dt.date(2024, 5, 1))
    login(client, "s@example.org")
    assert b"won the quiz" not in client.get(f"/children/{asha.id}?period=all").data


def test_filter_by_reporting_period(client, make_user, base_data):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    add_obs(staff, asha, base_data["cat"], "Older note from 2023.", dt.date(2023, 6, 1))
    add_obs(staff, asha, base_data["cat"], "Newer note from 2024.", dt.date(2024, 6, 1))
    login(client, "s@example.org")
    r = client.get(f"/children/{asha.id}?period={base_data['p24'].id}")
    assert b"Newer note" in r.data and b"Older note" not in r.data
    r = client.get(f"/children/{asha.id}?period={base_data['p23'].id}")
    assert b"Older note" in r.data and b"Newer note" not in r.data
    r = client.get(f"/children/{asha.id}?period=all")
    assert b"Older note" in r.data and b"Newer note" in r.data


def test_duplicate_observation_needs_confirmation(client, make_user, base_data):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    login(client, "s@example.org")
    url = f"/children/{asha.id}/observations/new"
    client.post(url, data=obs_form(base_data["cat"], text="Went to the temple."))
    r = client.post(url, data=obs_form(base_data["cat"], text="  - went  to the TEMPLE. "))
    assert r.status_code == 200
    db.session.expire_all()
    assert len(db.session.execute(db.select(Observation)).scalars().all()) == 1
    r = client.post(url, data=obs_form(base_data["cat"], text="Went to the temple.",
                                       confirm_duplicate="y"))
    assert r.status_code == 302


def test_future_date_is_rejected(client, make_user, base_data):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    login(client, "s@example.org")
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    r = client.post(f"/children/{asha.id}/observations/new",
                    data=obs_form(base_data["cat"], date=future))
    assert r.status_code == 200
    db.session.expire_all()
    assert db.session.execute(db.select(Observation)).first() is None


def test_edit_records_who_changed_it(client, make_user, base_data):
    staff = make_user("s@example.org")
    boss = make_user("boss@example.org", role=ROLE_ADMIN)
    asha = add_child(staff, "Asha", "Testperson")
    obs = add_obs(staff, asha, base_data["cat"], "First wording.", dt.date(2024, 2, 2))
    login(client, "boss@example.org")
    r = client.post(f"/observations/{obs.id}/edit", data=obs_form(
        base_data["cat"], text="Corrected wording.", date="2024-02-02",
        correction_note="Fixed after checking with the teacher"))
    assert r.status_code == 302
    db.session.expire_all()
    obs = db.session.get(Observation, obs.id)
    assert obs.text == "Corrected wording."
    assert obs.updated_by_id == boss.id
    assert obs.created_by_id == staff.id
    assert obs.child_id == asha.id
    assert obs.correction_note.startswith("Fixed")


def test_remove_hides_but_keeps_the_row(client, make_user, base_data):
    staff = make_user("s@example.org")
    asha = add_child(staff, "Asha", "Testperson")
    obs = add_obs(staff, asha, base_data["cat"], "A note to remove.", dt.date(2024, 2, 2))
    login(client, "s@example.org")
    assert client.post(f"/observations/{obs.id}/delete").status_code == 302
    db.session.expire_all()
    assert db.session.get(Observation, obs.id).is_deleted is True
    assert b"A note to remove" not in client.get(f"/children/{asha.id}?period=all").data


def test_staff_cannot_remove_someone_elses_observation(client, make_user, base_data):
    owner = make_user("owner@example.org")
    make_user("other@example.org")
    asha = add_child(owner, "Asha", "Testperson")
    obs = add_obs(owner, asha, base_data["cat"], "Owner's note.", dt.date(2024, 2, 2))
    login(client, "other@example.org")
    assert client.post(f"/observations/{obs.id}/delete").status_code == 403


# ---------- admin settings ----------
def test_staff_cannot_open_category_or_period_pages(client, make_user):
    make_user("s@example.org")
    login(client, "s@example.org")
    assert client.get("/admin/categories").status_code == 403
    assert client.get("/admin/periods").status_code == 403


def test_admin_can_add_category_and_period(client, make_user):
    make_user("boss@example.org", role=ROLE_ADMIN)
    login(client, "boss@example.org")
    r = client.post("/admin/categories/new", data={"name": "Festivals", "sort_order": "3", "is_active": "y"})
    assert r.status_code == 302
    r = client.post("/admin/periods/new", data={
        "year": "2025", "start_date": "2025-01-01", "end_date": "2025-12-31"})
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.execute(db.select(Category).filter_by(name="Festivals")).scalar_one()
    assert db.session.execute(db.select(ReportingPeriod).filter_by(year=2025)).scalar_one()
