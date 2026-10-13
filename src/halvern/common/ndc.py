"""National Drug Code (NDC) helpers."""

from pyspark.sql import Column
from pyspark.sql import functions as F

from halvern.common._columns import ColumnOrName, to_col

# NDC-10 forms with dashes, and how each is padded to the 5-4-2 NDC-11 layout.
_FORM_4_4_2 = r"^([0-9]{4})-([0-9]{4})-([0-9]{2})$"  # pad the labeler
_FORM_5_3_2 = r"^([0-9]{5})-([0-9]{3})-([0-9]{2})$"  # pad the product
_FORM_5_4_1 = r"^([0-9]{5})-([0-9]{4})-([0-9]{1})$"  # pad the package


def ndc10_to_ndc11(ndc10: ColumnOrName) -> Column:
    """Convert a dashed NDC-10 to an 11-digit NDC-11 without dashes.

    Values without dashes are ambiguous and give null, as does anything else that does not
    match one of the three NDC-10 forms.
    """
    c = F.trim(to_col(ndc10))

    def part(pattern: str, idx: int) -> Column:
        return F.regexp_extract(c, pattern, idx)

    return (
        F.when(
            c.rlike(_FORM_4_4_2),
            F.concat(F.lit("0"), part(_FORM_4_4_2, 1), part(_FORM_4_4_2, 2), part(_FORM_4_4_2, 3)),
        )
        .when(
            c.rlike(_FORM_5_3_2),
            F.concat(part(_FORM_5_3_2, 1), F.lit("0"), part(_FORM_5_3_2, 2), part(_FORM_5_3_2, 3)),
        )
        .when(
            c.rlike(_FORM_5_4_1),
            F.concat(part(_FORM_5_4_1, 1), part(_FORM_5_4_1, 2), F.lit("0"), part(_FORM_5_4_1, 3)),
        )
    )
