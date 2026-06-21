"""Form package — build schemas and collect QuerySpec from user input."""

from rf_finder.form.schema import Field, FormSchema, build_form
from rf_finder.form.input import collect

__all__ = ["Field", "FormSchema", "build_form", "collect"]
