import pytest
from werkzeug.middleware.proxy_fix import ProxyFix
from app import create_app
from app.ai.base import AIError, AIResult


def test_a_short_secret_key_is_refused_in_production(monkeypatch):
    monkeypatch.setattr("config.ProductionConfig.SECRET_KEY", "too-short")
    with pytest.raises(RuntimeError):
        create_app("production")


def test_production_uses_secure_cookies_and_hsts(monkeypatch):
    monkeypatch.setattr("config.ProductionConfig.SECRET_KEY", "x" * 48)
    app = create_app("production")
    assert app.config["SESSION_COOKIE_SECURE"] is True and not app.debug
    resp = app.test_client().get("/login")
    assert "max-age" in resp.headers["Strict-Transport-Security"]
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_proxy_trust_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    assert not isinstance(create_app("testing").wsgi_app, ProxyFix)
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert isinstance(create_app("testing").wsgi_app, ProxyFix)


class FakeProvider:
    def __init__(self, reply):
        self.reply = reply

    def generate(self, system_prompt, user_message):
        if isinstance(self.reply, Exception):
            raise self.reply
        return AIResult(text=self.reply, model="fake-model")


def test_ai_check_reports_success(app, monkeypatch):
    monkeypatch.setattr("app.ai.get_provider", lambda: FakeProvider("OK"))
    result = app.test_cli_runner().invoke(args=["ai-check"])
    assert result.exit_code == 0 and "Connected" in result.output and "fake-model" in result.output


def test_ai_check_explains_failures(app, monkeypatch):
    monkeypatch.setattr("app.ai.get_provider", lambda: FakeProvider(AIError("The AI model name was not found.", "model")))
    result = app.test_cli_runner().invoke(args=["ai-check"])
    assert result.exit_code != 0 and "model name was not found" in result.output


def test_backup_command_explains_that_sqlite_is_needed_for_the_in_memory_test_db(app):
    result = app.test_cli_runner().invoke(args=["backup"])
    assert result.exit_code != 0 and "SQLite" in result.output
