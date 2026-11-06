import subprocess
import sys
import zipfile
from pathlib import Path


def test_deploy_zip_leaves_out_secrets_data_and_tests():
    root = Path(__file__).resolve().parents[1]
    script = root / "tools" / "make_deploy_zip.py"
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    zip_path = root / "happy-report-app-deploy.zip"
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert "wsgi.py" in names and "requirements.txt" in names and "app/__init__.py" in names
        assert ".env.example" in names
        forbidden = [n for n in names if n == ".env" or n.endswith(".db") or n.startswith(("venv/", "instance/", "tests/", ".git/"))]
        assert forbidden == []
    finally:
        zip_path.unlink(missing_ok=True)
