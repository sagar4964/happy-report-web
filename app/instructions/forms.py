from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class InstructionForm(FlaskForm):
    note = StringField("What changed in this version? (optional)",
                       validators=[Optional(), Length(max=255)])
    prompt_text = TextAreaField("Report Writing Instructions",
                                validators=[DataRequired(), Length(min=200, max=60000)],
                                render_kw={"rows": 28})
