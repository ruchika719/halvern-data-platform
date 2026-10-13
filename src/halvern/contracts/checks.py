"""Row-level contract checks and in-file duplicate handling, as Spark expressions."""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from halvern.common import cast_seq, dedupe_latest, sap_date
from halvern.contracts import model as m
from halvern.contracts.readers import PARSE_ERROR, ROW_NUMBER

REASON_CODE = "_reason_code"
REASON_DETAIL = "_reason_detail"


def _sql_name(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def is_blank(spec: m.ColumnSpec) -> Column:
    """Null, empty or spaces; for SAP dates also ``00000000``."""
    c = F.col(spec.name)
    blank = c.isNull() | (F.trim(c.cast("string")) == "")
    if spec.base_type == "sap_date":
        blank = blank | (F.trim(c.cast("string")) == "00000000")
    return blank


def typed_value(spec: m.ColumnSpec) -> Column:
    """The value cast to the contract type, or null when it does not cast."""
    name = _sql_name(spec.name)
    if spec.base_type == "integer":
        return F.expr(f"try_cast(trim({name}) AS BIGINT)")
    if spec.base_type == "decimal":
        p, s = spec.decimal_precision_scale
        return F.expr(f"try_cast(trim({name}) AS DECIMAL({p},{s}))")
    if spec.base_type == "timestamp":
        return F.expr(f"try_cast({name} AS TIMESTAMP)")
    if spec.base_type == "sap_date":
        return sap_date(F.col(spec.name))
    if spec.base_type == "date":
        return F.try_to_timestamp(F.trim(F.col(spec.name)), F.lit(spec.format)).cast("date")
    return F.col(spec.name)


def type_ok(spec: m.ColumnSpec) -> Column:
    """True when a non-blank value has the contract type. Numbers must be plain digits."""
    text = F.trim(F.col(spec.name).cast("string"))
    ok = typed_value(spec).isNotNull()
    if spec.base_type == "integer":
        ok = ok & text.rlike(r"^-?[0-9]+$")
    if spec.base_type == "decimal":
        _, s = spec.decimal_precision_scale
        fraction = rf"(\.[0-9]{{1,{s}}})?" if s else ""
        ok = ok & text.rlike(rf"^-?[0-9]+{fraction}$")
    return ok


def _detail(spec: m.ColumnSpec) -> Column:
    value = F.coalesce(F.col(spec.name).cast("string"), F.lit("<null>"))
    return F.concat(F.lit(f"{spec.name}="), value)


def row_checks(contract: m.Contract) -> list[tuple[Column, str, Column]]:
    """(failing condition, reason code, detail) in priority order: the first match wins."""
    checks: list[tuple[Column, str, Column]] = [
        (F.col(PARSE_ERROR).isNotNull(), m.BAD_FORMAT, F.col(PARSE_ERROR))
    ]
    specs = contract.columns
    keys = set(contract.primary_key)
    for spec in specs:
        if spec.name in keys:
            checks.append((is_blank(spec), m.MISSING_KEY, _detail(spec)))

    # A delete row carries its key and technical columns; other fields may be empty.
    is_delete = F.lit(False)
    if contract.change_mode_column:
        is_delete = F.coalesce(F.col(contract.change_mode_column) == "D", F.lit(False))
    for spec in specs:
        if spec.required and spec.name not in keys:
            exempt = is_delete if not spec.name.startswith("_") else F.lit(False)
            checks.append((is_blank(spec) & ~exempt, m.MISSING_VALUE, _detail(spec)))

    for spec in specs:
        if spec.base_type != "string":
            checks.append((~is_blank(spec) & ~type_ok(spec), m.BAD_TYPE, _detail(spec)))
    for spec in specs:
        if spec.pattern:
            text = F.col(spec.name).cast("string")
            checks.append(
                (~is_blank(spec) & ~text.rlike(spec.pattern), m.BAD_FORMAT, _detail(spec))
            )
    for spec in specs:
        if spec.allowed is not None:
            in_list = F.col(spec.name).isin(list(spec.allowed))
            checks.append((~is_blank(spec) & ~in_list, m.BAD_VALUE, _detail(spec)))
    for spec in specs:
        value = typed_value(spec)
        if spec.min is not None:
            checks.append((~is_blank(spec) & (value < spec.min), m.OUT_OF_RANGE, _detail(spec)))
        if spec.max is not None:
            checks.append((~is_blank(spec) & (value > spec.max), m.OUT_OF_RANGE, _detail(spec)))
    return checks


def add_reasons(df: DataFrame, contract: m.Contract) -> DataFrame:
    """Add ``_reason_code`` and ``_reason_detail``; both are null for a valid row."""
    for spec in contract.columns:
        if spec.name not in df.columns:  # optional contract column absent from the file
            df = df.withColumn(spec.name, F.lit(None).cast("string"))
    checks = row_checks(contract)
    code = F.when(checks[0][0], F.lit(checks[0][1]))
    detail = F.when(checks[0][0], checks[0][2])
    for condition, reason, text in checks[1:]:
        code = code.when(condition, F.lit(reason))
        detail = detail.when(condition, text)
    return df.withColumn(REASON_CODE, code).withColumn(REASON_DETAIL, detail)


def drop_exact_duplicates(df: DataFrame, columns: list[str]) -> tuple[DataFrame, DataFrame]:
    """Split rows identical in every delivered column: (first occurrence, the extra copies)."""
    rn = "__dup_rn"
    ranked = df.withColumn(
        rn, F.row_number().over(Window.partitionBy(*columns).orderBy(ROW_NUMBER))
    )
    return ranked.where(F.col(rn) == 1).drop(rn), ranked.where(F.col(rn) > 1).drop(rn)


def keep_latest_per_key(df: DataFrame, contract: m.Contract) -> DataFrame:
    """One row per primary key: highest order columns (typed), then the later row in the file."""
    if not contract.primary_key:
        return df
    temp = []
    for i, name in enumerate(contract.order_columns):
        spec = contract.column(name)
        tmp = f"__order_{i}"
        if spec.base_type == "integer":
            df = cast_seq(df.withColumn(tmp, F.col(name)), seq_col=tmp)
        else:
            df = df.withColumn(tmp, typed_value(spec))
        temp.append(tmp)
    latest = dedupe_latest(df, list(contract.primary_key), [*temp, ROW_NUMBER])
    return latest.drop(*temp)
