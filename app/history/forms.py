from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import IntegerField
from wtforms.validators import DataRequired, NumberRange


class HistoryUploadForm(FlaskForm):
    reporting_year = IntegerField("Year this report covers (for example 2025)",
                                  validators=[DataRequired(), NumberRange(min=2000, max=2100)])
    file = FileField("Report file (.docx; a .pdf can be added for reference)",
                     validators=[FileRequired()])
