from conftest import login


def test_test_mode_banner_shows_only_when_switched_on(client, make_user, monkeypatch):
    make_user("s@example.org")
    login(client, "s@example.org")
    monkeypatch.delenv("AI_TEST_MODE", raising=False)
    assert b"TEST MODE" not in client.get("/").data
    monkeypatch.setenv("AI_TEST_MODE", "1")
    assert b"TEST MODE" in client.get("/").data
