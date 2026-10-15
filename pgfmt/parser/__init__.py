"""The Parser class, assembled from the statement-family mixins in this package."""

from __future__ import annotations
from .base import BaseParserMixin
from .ddl import DdlParserMixin
from .dml import DmlParserMixin
from .expressions import ExpressionParserMixin
from .select import SelectParserMixin


class Parser(BaseParserMixin, ExpressionParserMixin, SelectParserMixin, DmlParserMixin, DdlParserMixin):
    """Recursive-descent parser (statements) + Pratt parser (expressions): tokens -> AST.

    The methods live in the mixins, one file per statement family.
    """
