# Happy Children Nepal - Annual Sponsor Report Writer (Phase 2)

## Windows setup (PowerShell in VS Code, inside this folder)
    python -m venv venv
    venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    copy .env.example .env
    python -c "import secrets; print(secrets.token_hex(32))"   # paste result as SECRET_KEY in .env

## Create the database and first admin
    flask --app run db init
    flask --app run db migrate -m "users and audit events"
    flask --app run db upgrade
    flask --app run create-admin

## Run
    flask --app run run --debug      # then open http://127.0.0.1:5000

## Tests
    pytest
