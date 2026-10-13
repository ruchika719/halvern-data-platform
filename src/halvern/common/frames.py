"""DataFrame transformations."""

from collections.abc import Sequence
from functools import reduce

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

# Joins hashed values; a control character that does not occur in source data.
ROW_HASH_SEPARATOR = "\u001f"
# Stands in for null so that null and the empty string hash differently.
ROW_HASH_NULL = "\u0000"


def dedupe_latest(df: DataFrame, keys: Sequence[str], order_cols: Sequence[str]) -> DataFrame:
    """Keep one row per key: the row with the highest ``order_cols``, compared left to right.

    Rows with a null in any key column are dropped. Order columns must already have their real
    types (for example ``_seq`` as an integer), because text sorts ``"10"`` before ``"9"``.
    """
    if not keys or not order_cols:
        raise ValueError("keys and order_cols must not be empty")
    not_null = reduce(lambda a, b: a & b, [F.col(k).isNotNull() for k in keys])
    window = Window.partitionBy(*keys).orderBy(*[F.col(c).desc_nulls_last() for c in order_cols])
    rn = "__dedupe_rn"
    return (
        df.where(not_null)
        .withColumn(rn, F.row_number().over(window))
        .where(F.col(rn) == 1)
        .drop(rn)
    )


def row_hash(df: DataFrame, cols: Sequence[str], output_col: str = "_row_hash") -> DataFrame:
    """Add ``output_col``: SHA-256 (hex) of ``cols`` joined in the given order.

    Nulls are hashed as ``\\u0000``, so null and the empty string differ, and column order
    matters.
    """
    if not cols:
        raise ValueError("cols must not be empty")
    parts = [F.coalesce(F.col(c).cast("string"), F.lit(ROW_HASH_NULL)) for c in cols]
    return df.withColumn(output_col, F.sha2(F.concat_ws(ROW_HASH_SEPARATOR, *parts), 256))
