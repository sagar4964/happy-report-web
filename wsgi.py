"""Entry point for hosting services such as PythonAnywhere."""
import os

os.environ.setdefault("APP_ENV", "production")

from app import create_app  # noqa: E402

application = create_app()
