"""Small internal helpers shared by the column functions."""

from pyspark.sql import Column
from pyspark.sql import functions as F

ColumnOrName = Column | str


def to_col(col: ColumnOrName) -> Column:
    """Accept a Column or a column name."""
    return F.col(col) if isinstance(col, str) else col
