import pytest
from app import create_app
from app.extensions import db
from app.models import User, ROLE_STAFF

PASSWORD = "correct-horse-battery"


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user():
    def _make(email, role=ROLE_STAFF, is_active=True):
        user = User(name="Test User", email=email, role=role, is_active=is_active)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user
    return _make


def login(client, email, password=PASSWORD, next_url=None):
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"email": email, "password": password})
