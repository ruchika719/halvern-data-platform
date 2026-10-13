"""Unit tests for halvern.common.ndc."""

import pytest
from pyspark.sql import functions as F

from halvern.common import ndc10_to_ndc11

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("ndc10", "expected"),
    [
        ("1234-5678-90", "01234567890"),  # 4-4-2: pad the labeler
        ("12345-678-90", "12345067890"),  # 5-3-2: pad the product
        ("12345-6789-0", "12345678900"),  # 5-4-1: pad the package
        ("12345-678-90   ", "12345067890"),  # Pacifica pads with spaces
        ("1234567890", None),  # no dashes: ambiguous
        ("ABCDE-123-45", None),
        ("123-4567-890", None),
        ("", None),
        (None, None),
    ],
)
def test_ndc10_to_ndc11(spark, ndc10, expected):
    df = spark.createDataFrame([(ndc10,)], "v string")
    assert df.select(ndc10_to_ndc11(F.col("v")).alias("out")).first().out == expected
