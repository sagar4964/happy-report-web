from datetime import date
from pathlib import Path
import click
from .extensions import db
from .models import User, ROLE_ADMIN, Category, ReportingPeriod, ReportTemplate

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
