"""Tests for loading and validating contract YAML."""

import copy

import pytest
import yaml

from halvern.contracts import ContractError, load_contract, parse_contract

pytestmark = pytest.mark.contract

EXPECTED = {
    "sap_kna1",
    "sap_knvv",
    "sap_mara",
    "sap_makt",
    "sap_vbrk",
    "sap_vbrp",
    "sap_tcurr",
    "wholesaler_northline_867",
    "wholesaler_pacifica_867",
    "wholesaler_crestway_867",
    "reference_wholesaler_item_xref",
}

TECHNICAL = ["_op", "_change_ts", "_seq", "_extract_id", "_source_system"]


def test_every_source_object_has_a_contract(contracts):
    assert set(contracts) == EXPECTED


def test_sap_contracts_are_parquet_with_technical_columns(contracts):
    for name, contract in contracts.items():
        if name.startswith("sap_"):
            assert contract.format == "parquet"
            assert list(contract.column_names[-5:]) == TECHNICAL
            assert contract.order_columns == ("_change_ts", "_seq")
            assert contract.column("_change_ts").type == "timestamp"


def test_wholesaler_contracts_need_control_files(contracts):
    for name, contract in contracts.items():
        assert contract.control_file == name.startswith("wholesaler_")


def test_vbrk_matches_spec_example(contracts):
    vbrk = contracts["sap_vbrk"]
    assert vbrk.primary_key == ("VBELN",)
    assert vbrk.allow_new_columns is True
    assert vbrk.allow_empty is False
    assert vbrk.business_date_column == "FKDAT"
    assert vbrk.column("FKART").allowed == ("F2", "L2", "G2", "RE", "S1", "IV")
    assert vbrk.column("NETWR").decimal_precision_scale == (15, 2)


def test_pacifica_positions_cover_55_characters(contracts):
    pacifica = contracts["wholesaler_pacifica_867"]
    assert pacifica.record_length == 55
    assert pacifica.positions[0].start == 1
    assert pacifica.positions[-1].end == 55
    assert pacifica.positions[-1].name == "sign"


def base():
    return {
        "name": "t",
        "version": 1,
        "owner": "me",
        "landing_path": "x/",
        "format": "csv",
        "delimiter": ",",
        "primary_key": ["id"],
        "columns": [{"name": "id", "type": "string", "required": True}],
    }


def test_minimal_contract_loads(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text(yaml.safe_dump(base()))
    contract = load_contract(path)
    assert contract.name == "t"
    assert contract.header is True
    assert contract.encoding == "utf-8"


def mutate(change):
    data = copy.deepcopy(base())
    change(data)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(colour="red"), "unknown key"),
        (lambda d: d["columns"][0].update(nullable=True), "unknown key"),
        (lambda d: d["columns"][0].update(type="varchar"), "unknown type"),
        (lambda d: d.update(format="xml"), "format must be"),
        (lambda d: d.pop("owner"), "missing key"),
        (lambda d: d.update(version="1"), "version must be int"),
        (lambda d: d.update(version=True), "version must be int"),
        (lambda d: d.update(primary_key=["nope"]), "unknown column"),
        (lambda d: d.update(order_columns=["nope"]), "unknown column"),
        (lambda d: d["columns"][0].update(required=False), "must be required"),
        (lambda d: d["columns"][0].update(allowed=[True, "X"]), "must be str"),
        (lambda d: d["columns"][0].update(pattern="(["), "invalid pattern"),
        (lambda d: d["columns"][0].update(min=0), "needs an integer or decimal"),
        (lambda d: d["columns"][0].update(type="date"), "needs a format"),
        (lambda d: d["columns"][0].update(format="yyyy"), "only allowed for type date"),
        (lambda d: d["columns"].append({"name": "id", "type": "string"}), "duplicate column"),
        (lambda d: d.update(delimiter=",,"), "one character"),
        (lambda d: d.update(landing_path="x/{date}/"), "placeholder"),
        (lambda d: d.update(landing_path="x"), "must end with /"),
        (lambda d: d.update(landing_path="{source_system}/"), "source_system is not set"),
        (lambda d: d.update(control_file=True), "control_qty_column"),
        (lambda d: d.update(format="parquet"), "unknown key"),  # delimiter not allowed
    ],
)
def test_invalid_contracts_fail(change, message):
    with pytest.raises(ContractError, match=message):
        parse_contract(mutate(change))


def fixed_width(positions):
    data = base()
    del data["delimiter"]
    data.update(format="fixed_width", record_length=5, positions=positions)
    return data


def test_fixed_width_positions_must_match_columns():
    with pytest.raises(ContractError, match="exactly the columns"):
        parse_contract(fixed_width([{"name": "other", "start": 1, "end": 5}]))


def test_fixed_width_positions_must_fit_the_record():
    with pytest.raises(ContractError, match="out of range"):
        parse_contract(fixed_width([{"name": "id", "start": 1, "end": 6}]))


def test_decimal_and_numeric_bounds_load():
    data = base()
    data["columns"].append({"name": "amount", "type": "decimal(15,2)", "min": 0, "max": 10.5})
    spec = parse_contract(data).column("amount")
    assert spec.base_type == "decimal"
    assert (spec.min, spec.max) == (0, 10.5)
