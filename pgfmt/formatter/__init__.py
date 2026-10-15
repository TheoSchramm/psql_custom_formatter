"""The ASTFormatter class, assembled from the statement-family mixins in this package."""

from __future__ import annotations
from .base import BaseFormatterMixin
from .ddl import DdlFormatterMixin
from .dml import DmlFormatterMixin
from .expressions import ExpressionFormatterMixin
from .select import SelectFormatterMixin


class ASTFormatter(BaseFormatterMixin, ExpressionFormatterMixin, SelectFormatterMixin, DmlFormatterMixin, DdlFormatterMixin):
    """AST walker -> formatted SQL text.

    The methods live in the mixins, one file per statement family.
    """
