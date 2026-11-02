from app.extensions import db
from app.models import ROLE_ADMIN
from conftest import login, PASSWORD


def test_anonymous_is_redirected_to_login(client):
    r = client.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_login_success(client, make_user):
    make_user("a@example.org")
    assert login(client, "a@example.org").status_code == 302
    assert client.get("/").status_code == 200


def test_wrong_password_is_rejected(client, make_user):
    make_user("a@example.org")
    r = login(client, "a@example.org", "wrong-password-123")
    assert r.status_code == 200 and b"Invalid email or password" in r.data


def test_inactive_user_cannot_log_in(client, make_user):
    make_user("a@example.org", is_active=False)
    r = login(client, "a@example.org")
    assert r.status_code == 200
    assert client.get("/").status_code == 302


def test_password_is_hashed(app, make_user):
    user = make_user("a@example.org")
    assert user.password_hash != PASSWORD


def test_staff_cannot_open_admin_pages(client, make_user):
    make_user("staff@example.org")
    login(client, "staff@example.org")
    assert client.get("/admin/users").status_code == 403


def test_admin_can_open_admin_pages(client, make_user):
    make_user("boss@example.org", role=ROLE_ADMIN)
    login(client, "boss@example.org")
    assert client.get("/admin/users").status_code == 200


def test_anonymous_cannot_open_admin_pages(client):
    assert client.get("/admin/users").status_code == 302


def test_logout_requires_post(client, make_user):
    make_user("a@example.org")
    login(client, "a@example.org")
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 302
    assert client.get("/").status_code == 302


def test_open_redirect_is_blocked(client, make_user):
    make_user("a@example.org")
    r = login(client, "a@example.org", next_url="https://evil.example")
    assert not r.headers["Location"].startswith("https://evil.example")


def test_deactivated_user_is_logged_out_on_next_request(client, make_user):
    user = make_user("a@example.org")
    login(client, "a@example.org")
    user.is_active = False
    db.session.commit()
    assert client.get("/").status_code == 302
