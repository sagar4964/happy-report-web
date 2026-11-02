import click
from .extensions import db
from .models import User, ROLE_ADMIN


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
