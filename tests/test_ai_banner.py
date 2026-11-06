from conftest import login


def test_the_red_test_mode_bar_is_gone(client, make_user, monkeypatch):
    make_user("s@example.org")
    login(client, "s@example.org")
    monkeypatch.setenv("AI_TEST_MODE", "1")  # even if an old setting is still in .env
    assert b"TEST MODE" not in client.get("/").data
