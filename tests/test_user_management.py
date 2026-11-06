"""Deactivating and removing accounts. All accounts and names are fictional."""
import pytest
from app.extensions import db
from app.models import AuditEvent, Child, User, ROLE_ADMIN, ROLE_STAFF
from app.user_admin import is_removed
from conftest import login, PASSWORD


@pytest.fixture
def team(make_user):
    admin = make_user("boss@example.org", role=ROLE_ADMIN)
    staff = make_user("writer@example.org")
    return admin, staff


def state(user_id):
    db.session.expire_all()
    return db.session.get(User, user_id)


def test_an_admin_can_deactivate_and_reactivate_someone(client, team):
    admin, staff = team
    login(client, "boss@example.org")
    assert client.post(f"/admin/users/{staff.id}/deactivate").status_code == 302
    assert state(staff.id).is_active is False
    client.post("/logout")

    login(client, "writer@example.org")                      # cannot log in any more
    assert client.get("/children/").status_code == 302

    login(client, "boss@example.org")
    client.post(f"/admin/users/{staff.id}/reactivate")
    assert state(staff.id).is_active is True
    client.post("/logout")
    login(client, "writer@example.org")
    assert client.get("/children/").status_code == 200


def test_nobody_can_deactivate_or_remove_their_own_account(client, team):
    admin, _staff = team
    login(client, "boss@example.org")
    client.post(f"/admin/users/{admin.id}/deactivate")
    client.post(f"/admin/users/{admin.id}/remove")
    me = state(admin.id)
    assert me is not None and me.is_active is True and me.role == ROLE_ADMIN and not is_removed(me)


def test_staff_cannot_manage_accounts(client, team):
    admin, staff = team
    login(client, "writer@example.org")
    for action in ("deactivate", "reactivate", "remove"):
        assert client.post(f"/admin/users/{admin.id}/{action}").status_code == 403
    assert state(admin.id).is_active is True


def test_an_account_that_was_never_used_is_deleted_completely(client, team, make_user):
    admin, _staff = team
    unused = make_user("typo@example.org")
    unused_id = unused.id
    login(client, "boss@example.org")
    client.post(f"/admin/users/{unused_id}/remove")
    assert state(unused_id) is None


def test_removing_someone_who_worked_keeps_their_work(client, team):
    admin, staff = team
    child = Child(first_name="Asha", last_name="Testperson", current_education="Class 6", created_by_id=staff.id)
    db.session.add(child)
    db.session.commit()
    child_id = child.id

    login(client, "boss@example.org")
    client.post(f"/admin/users/{staff.id}/remove")
    gone = state(staff.id)
    assert gone is not None and gone.name == "Removed user" and is_removed(gone)
    assert gone.email.endswith("@removed.invalid") and gone.is_active is False and gone.role == ROLE_STAFF
    assert db.session.get(Child, child_id).created_by_id == staff.id           # their work is untouched

    page = client.get("/admin/users").data
    assert b"writer@example.org" not in page and b"removed.invalid" not in page   # hidden from the normal list
    assert b"removed.invalid" in client.get("/admin/users?show_removed=1").data
    client.post("/logout")
    login(client, "writer@example.org", PASSWORD)                              # the old login is dead
    assert client.get("/children/").status_code == 302


def test_a_removed_account_cannot_be_edited_or_brought_back(client, team):
    admin, staff = team
    db.session.add(Child(first_name="Asha", last_name="T", current_education="Class 6", created_by_id=staff.id))
    db.session.commit()
    login(client, "boss@example.org")
    client.post(f"/admin/users/{staff.id}/remove")
    assert client.get(f"/admin/users/{staff.id}/edit").status_code == 302
    client.post(f"/admin/users/{staff.id}/reactivate")
    assert state(staff.id).is_active is False


def test_every_account_action_is_recorded(client, team):
    admin, staff = team
    login(client, "boss@example.org")
    client.post(f"/admin/users/{staff.id}/deactivate")
    client.post(f"/admin/users/{staff.id}/reactivate")
    client.post(f"/admin/users/{staff.id}/remove")
    db.session.expire_all()
    actions = {a.action for a in db.session.execute(db.select(AuditEvent)).scalars()}
    assert {"user_deactivated", "user_reactivated", "user_removed"} <= actions


def test_the_users_page_and_the_old_edit_form_still_work(client, team):
    admin, staff = team
    login(client, "boss@example.org")
    page = client.get("/admin/users").data
    assert b"writer@example.org" in page and b"Deactivate" in page and b"Remove" in page
    r = client.post(f"/admin/users/{staff.id}/edit", data={"name": "Writer Renamed", "role": ROLE_STAFF, "is_active": "y"})
    assert r.status_code == 302 and state(staff.id).name == "Writer Renamed"
