"""Column helpers for SAP-formatted text values.

Every function takes and returns a Spark Column and uses only built-in Spark functions.
"""

from collections.abc import Mapping
from decimal import Decimal

from pyspark.sql import Column
from pyspark.sql import functions as F

from halvern.common._columns import ColumnOrName, to_col

# Billing type (FKART) to sign. NETWR and FKIMG are always positive; the sign comes from here.
BILLING_SIGNS: Mapping[str, int] = {
    "F2": 1,
    "L2": 1,
    "IV": 1,
    "G2": -1,
    "RE": -1,
    "S1": -1,
}


def _blank_to_null(c: Column) -> Column:
    return F.when(F.trim(c) == "", F.lit(None)).otherwise(c)


def strip_sap_zeros(col: ColumnOrName) -> Column:
    """Remove leading zeros from an all-digit SAP key.

    All zeros become ``"0"``, alphanumeric values are unchanged, blank or null becomes null.
    """
    c = _blank_to_null(to_col(col))
    trimmed = F.trim(c)
    return F.when(
        trimmed.rlike("^[0-9]+$"),
        F.regexp_replace(trimmed, "^0+(?=[0-9])", ""),
    ).otherwise(c)


def sap_date(col: ColumnOrName) -> Column:
    """Convert SAP ``YYYYMMDD`` text to a date.

    ``00000000``, blank, null and invalid dates (such as ``20261345``) become null.
    """
    c = F.trim(to_col(col))
    parsed = F.try_to_timestamp(c, F.lit("yyyyMMdd")).cast("date")
    return F.when(c.rlike("^[0-9]{8}$") & (c != "00000000"), parsed)


def invert_gdatu(col: ColumnOrName) -> Column:
    """Convert a TCURR ``GDATU`` (stored as ``99999999 - YYYYMMDD``) to a date."""
    c = F.trim(to_col(col))
    inverted = F.lpad((F.lit(99999999) - c.cast("int")).cast("string"), 8, "0")
    return F.when(c.rlike("^[0-9]{8}$"), sap_date(inverted))


def currency_shift(
    amount: ColumnOrName,
    currency: ColumnOrName,
    decimals_map: Mapping[str, int],
) -> Column:
    """Convert an SAP amount to the real amount: ``amount * 10^(2 - decimals)``.

    SAP stores every amount with two decimals; ``decimals_map`` gives the real number of
    decimals per currency (for example ``{"JPY": 0}``). Currencies not in the map use 2.
    Returns ``decimal(24,4)``.
    """
    cur = to_col(currency)
    factor = F.lit(Decimal(1))
    for code, decimals in decimals_map.items():
        factor = F.when(cur == code, F.lit(Decimal(10) ** (2 - decimals))).otherwise(factor)
    return (to_col(amount).cast("decimal(18,2)") * factor).cast("decimal(24,4)")


def sap_rate(ukurs: ColumnOrName, ffact: ColumnOrName, tfact: ColumnOrName) -> Column:
    """Units of TCURR per one unit of FCURR, from SAP's TCURR fields.

    A negative ``UKURS`` is an indirect quote (rate = 1 / |UKURS|). The rate is then scaled by
    ``TFACT / FFACT``. A zero or null input gives null. Returns ``decimal(24,10)``.
    """
    u = to_col(ukurs).cast("decimal(18,9)")
    ff = to_col(ffact).cast("decimal(18,9)")
    tf = to_col(tfact).cast("decimal(18,9)")
    base = F.when(u < 0, F.lit(Decimal(1)) / F.abs(u)).otherwise(u)
    rate = base * tf / ff
    return F.when((u != 0) & (ff != 0), rate.cast("decimal(24,10)"))


def billing_sign(fkart: ColumnOrName, signs: Mapping[str, int] = BILLING_SIGNS) -> Column:
    """+1 or -1 for a billing type (FKART); unknown types give null."""
    c = to_col(fkart)
    result = F.lit(None).cast("int")
    for code, sign in signs.items():
        result = F.when(c == code, F.lit(sign)).otherwise(result)
    return result
