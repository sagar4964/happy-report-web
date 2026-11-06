from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from .periods import VIEWS, today_in_nepal, parse_anchor
from .stats import contribution_table, METRICS

bp = Blueprint("contributions", __name__, url_prefix="/contributions")


@bp.route("/")
@login_required
def index():
    view = request.args.get("view", "month")
    if view not in VIEWS:
        view = "month"
    today = today_in_nepal()
    anchor = parse_anchor(request.args.get("date"), today)
    data = contribution_table(view, anchor, today)
    rows = data["rows"]
    if not current_user.is_admin:
        rows = [r for r in rows if r["user"].id == current_user.id]   # staff see only their own numbers
    return render_template("contributions/index.html", view=view, anchor=anchor, rows=rows,
                           metrics=METRICS, label=data["label"], team_total=data["team_total"],
                           previous_anchor=data["previous_anchor"], next_anchor=data["next_anchor"])
