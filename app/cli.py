from datetime import date
from pathlib import Path
import click
from .extensions import db
from .backup import create_backup, restore_backup, BackupError
from .retention import delete_child_permanently
from .models import User, ROLE_ADMIN, Category, ReportingPeriod, ReportTemplate, Child

DEFAULT_CATEGORIES = [
    "Education and examinations",
    "Activities and achievements",
    "Personality and everyday behaviour",
    "Friendships and relationships",
    "Family events",
    "Emotional or behavioural challenges",
    "Health or wellbeing (only where necessary)",
    "Interests and future plans",
    "Support from carers or teachers",
    "Festivals, visits and special occasions",
    "Other",
]


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--email", prompt="Email")
    @click.password_option(prompt="Password (min 12 characters)")
    def create_admin(name, email, password):
        """Create an administrator account."""
        email = email.strip().lower()
        if len(password) < 12:
            raise click.ClickException("Password must be at least 12 characters.")
        exists = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if exists:
            raise click.ClickException("A user with that email already exists.")
        user = User(name=name.strip(), email=email, role=ROLE_ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Administrator created.")

    @app.cli.command("seed-defaults")
    def seed_defaults():
        """Add the starter categories and this year's reporting period (safe to repeat)."""
        added = 0
        for order, name in enumerate(DEFAULT_CATEGORIES, start=1):
            exists = db.session.execute(db.select(Category).filter_by(name=name)).scalar_one_or_none()
            if not exists:
                db.session.add(Category(name=name, sort_order=order))
                added += 1
        year = date.today().year
        has_period = db.session.execute(db.select(ReportingPeriod).filter_by(year=year)).scalar_one_or_none()
        if not has_period:
            db.session.add(ReportingPeriod(year=year, start_date=date(year, 1, 1), end_date=date(year, 12, 31)))
            click.echo(f"Added reporting period {year} (1 Jan - 31 Dec). Edit it in Admin > Periods if yours differs.")
        if not db.session.execute(db.select(ReportTemplate)).first():
            prompt_file = Path(__file__).resolve().parent / "prompts" / "report_prompt_v1.txt"
            db.session.add(ReportTemplate(
                version_number=1, is_active=True,
                note="Original report-writing prompt supplied by the organization",
                prompt_text=prompt_file.read_text(encoding="utf-8")))
            click.echo("Saved report-writing instructions as version 1.")
        db.session.commit()
        click.echo(f"Added {added} new categories.")


    def _database_file():
        """Path of the SQLite file (backup and restore support SQLite only)."""
        url = db.engine.url
        if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
            raise click.ClickException(
                "Automatic backup supports the SQLite database only. "
                "For PostgreSQL use the pg_dump program instead.")
        path = Path(url.database)
        return path if path.is_absolute() else Path(app.instance_path) / path

    def _backups_folder():
        return Path(app.instance_path) / "backups"

    @app.cli.command("backup")
    def backup_command():
        """Create a backup zip of the database and all stored files."""
        try:
            target = create_backup(_database_file(), app.config["UPLOAD_FOLDER"], _backups_folder())
        except BackupError as e:
            raise click.ClickException(str(e))
        click.echo(f"Backup created: {target}")
        click.echo("It contains information about children. Download it, store it safely, "
                   "and delete old copies you no longer need.")

    @app.cli.command("restore")
    @click.argument("backup_file", type=click.Path(exists=True, dir_okay=False))
    @click.option("--yes", is_flag=True, help="Confirm that the current data may be replaced.")
    def restore_command(backup_file, yes):
        """Replace ALL current data with a backup. Stop or reload the web app afterwards."""
        if not yes:
            raise click.ClickException(
                "This replaces ALL current data with the backup. Run again with --yes to confirm.")
        db.session.remove()
        db.engine.dispose()
        try:
            safety = create_backup(_database_file(), app.config["UPLOAD_FOLDER"], _backups_folder())
            click.echo(f"Safety copy of the current data saved first: {safety}")
            restored = restore_backup(backup_file, _database_file(), app.config["UPLOAD_FOLDER"])
        except BackupError as e:
            raise click.ClickException(str(e))
        click.echo(f"Restored the database and {restored} stored file(s). "
                   "Reload the web app and check that you can log in.")

    @app.cli.command("delete-child")
    @click.argument("child_id", type=int)
    def delete_child_command(child_id):
        """PERMANENTLY delete one child and all linked data and files."""
        child = db.session.get(Child, child_id)
        if child is None:
            raise click.ClickException("No child with that ID.")
        click.echo(f"This will PERMANENTLY delete {child.full_name} (ID {child.id}) and every observation, "
                   "previous report, generated report and Word file linked to this child.")
        click.echo("It cannot be undone. Run 'flask --app run backup' first if you are not sure.")
        typed = click.prompt("Type the child's full name to confirm")
        if typed.strip().lower() != child.full_name.lower():
            raise click.ClickException("The name did not match. Nothing was deleted.")
        counts = delete_child_permanently(child_id)
        click.echo(f"Deleted. {counts}")

    @app.cli.command("ai-check")
    def ai_check_command():
        """Send one tiny fictional message to the AI to test the key, model and connection."""
        from . import ai
        from .ai.base import AIError
        try:
            result = ai.get_provider().generate(
                "You are a connection test. Reply with the single word OK.", "Please reply now.")
        except AIError as e:
            raise click.ClickException(e.user_message)
        click.echo(f"Connected. Model: {result.model}. Reply: {result.text[:80]}")
