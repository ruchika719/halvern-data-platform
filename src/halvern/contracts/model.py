"""Data contract model and loader (spec 01 section 6, change request 01a section 5)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# File-level reason codes: any of these rejects the whole file or run.
ENCODING_ERROR = "encoding_error"
MISSING_COLUMN = "missing_column"
UNEXPECTED_COLUMN = "unexpected_column"
EMPTY_FILE = "empty_file"
CORRUPT_FILE = "corrupt_file"
BAD_RECORD_LENGTH = "bad_record_length"
INCOMPLETE_RUN = "incomplete_run"
FAILED_RUN = "failed_run"
CONTROL_MISMATCH = "control_mismatch"

# Row-level reason codes: the row goes to quarantine.
MISSING_KEY = "missing_key"
MISSING_VALUE = "missing_value"
BAD_TYPE = "bad_type"
BAD_FORMAT = "bad_format"
BAD_VALUE = "bad_value"
OUT_OF_RANGE = "out_of_range"

# Duplicates inside one file: counted, not quarantined.
DUPLICATE_ROW = "duplicate_row"
KEY_COLLISION = "key_collision"

# Warnings.
SCHEMA_DRIFT = "schema_drift"

FORMATS = ("csv", "fixed_width", "parquet")
_DECIMAL_RE = re.compile(r"^decimal\((\d+),(\d+)\)$")
_SIMPLE_TYPES = ("string", "sap_date", "date", "timestamp", "integer")
_NUMERIC_TYPES = ("integer", "decimal")

_COMMON_KEYS = {
    "name",
    "version",
    "owner",
    "description",
    "source_system",
    "landing_path",
    "format",
    "allow_empty",
    "allow_new_columns",
    "primary_key",
    "change_mode_column",
    "order_columns",
    "business_date_column",
    "arrival",
    "columns",
}
_TEXT_KEYS = {
    "file_pattern",
    "encoding",
    "control_file",
    "control_qty_column",
    "control_qty_sign_column",
}
_FORMAT_KEYS = {
    "csv": _COMMON_KEYS | _TEXT_KEYS | {"delimiter", "header"},
    "fixed_width": _COMMON_KEYS | _TEXT_KEYS | {"record_length", "positions"},
    "parquet": _COMMON_KEYS,
}
_REQUIRED_KEYS = {"name", "version", "owner", "landing_path", "format", "primary_key", "columns"}
_COLUMN_KEYS = {"name", "type", "required", "pattern", "allowed", "min", "max", "format"}
_POSITION_KEYS = {"name", "start", "end"}


class ContractError(ValueError):
    """The contract YAML itself is invalid."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str
    required: bool = False
    pattern: str | None = None
    allowed: tuple[str, ...] | None = None
    min: float | None = None
    max: float | None = None
    format: str | None = None

    @property
    def base_type(self) -> str:
        return "decimal" if self.type.startswith("decimal") else self.type

    @property
    def decimal_precision_scale(self) -> tuple[int, int] | None:
        m = _DECIMAL_RE.match(self.type)
        return (int(m.group(1)), int(m.group(2))) if m else None


@dataclass(frozen=True)
class Position:
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class Contract:
    name: str
    version: int
    owner: str
    landing_path: str
    format: str
    primary_key: tuple[str, ...]
    columns: tuple[ColumnSpec, ...]
    description: str | None = None
    source_system: tuple[str, ...] = ()
    file_pattern: str | None = None
    encoding: str = "utf-8"
    delimiter: str | None = None
    header: bool = True
    record_length: int | None = None
    positions: tuple[Position, ...] = ()
    allow_empty: bool = False
    allow_new_columns: bool = False
    change_mode_column: str | None = None
    order_columns: tuple[str, ...] = ()
    business_date_column: str | None = None
    arrival: str | None = None
    control_file: bool = False
    control_qty_column: str | None = None
    control_qty_sign_column: str | None = None
    path: str | None = field(default=None, compare=False)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.required)

    def column(self, name: str) -> ColumnSpec:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)


def _fail(path: Any, message: str) -> None:
    raise ContractError(f"{path}: {message}")


def _check_keys(path: Any, where: str, data: dict, allowed: set[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        _fail(path, f"unknown key(s) in {where}: {', '.join(unknown)}")


def _expect(path: Any, name: str, value: Any, kind: type | tuple[type, ...]) -> Any:
    # bool is an int subclass; keep the two apart so `version: true` fails.
    if isinstance(value, bool) and kind is int:
        _fail(path, f"{name} must be {kind.__name__}, got {value!r}")
    if not isinstance(value, kind):
        expected = kind.__name__ if isinstance(kind, type) else "/".join(k.__name__ for k in kind)
        _fail(path, f"{name} must be {expected}, got {value!r}")
    return value


def _str_list(path: Any, name: str, value: Any) -> tuple[str, ...]:
    _expect(path, name, value, list)
    for item in value:
        # YAML turns unquoted yes/no/on/off into booleans; catch that here.
        _expect(path, f"{name} item", item, str)
    return tuple(value)


def _parse_column(path: Any, raw: Any) -> ColumnSpec:
    _expect(path, "column", raw, dict)
    _check_keys(path, f"column {raw.get('name')!r}", raw, _COLUMN_KEYS)
    name = _expect(path, "column name", raw.get("name"), str)
    col_type = _expect(path, f"type of {name}", raw.get("type"), str)
    if col_type not in _SIMPLE_TYPES and not _DECIMAL_RE.match(col_type):
        _fail(path, f"column {name}: unknown type {col_type!r}")
    required = _expect(path, f"required of {name}", raw.get("required", False), bool)
    pattern = raw.get("pattern")
    if pattern is not None:
        _expect(path, f"pattern of {name}", pattern, str)
        try:
            re.compile(pattern)
        except re.error as exc:
            _fail(path, f"column {name}: invalid pattern: {exc}")
    allowed = raw.get("allowed")
    if allowed is not None:
        allowed = _str_list(path, f"allowed of {name}", allowed)
    spec = ColumnSpec(
        name=name,
        type=col_type,
        required=required,
        pattern=pattern,
        allowed=allowed,
        min=raw.get("min"),
        max=raw.get("max"),
        format=raw.get("format"),
    )
    for bound in ("min", "max"):
        value = getattr(spec, bound)
        if value is not None:
            if spec.base_type not in _NUMERIC_TYPES:
                _fail(path, f"column {name}: {bound} needs an integer or decimal type")
            _expect(path, f"{bound} of {name}", value, (int, float))
    if spec.base_type == "date":
        if not isinstance(spec.format, str):
            _fail(path, f"column {name}: type date needs a format, such as yyyy-MM-dd")
    elif spec.format is not None:
        _fail(path, f"column {name}: format is only allowed for type date")
    return spec


def _parse_positions(path: Any, raw: Any, record_length: int) -> tuple[Position, ...]:
    _expect(path, "positions", raw, list)
    positions = []
    last_end = 0
    for item in raw:
        _expect(path, "position", item, dict)
        _check_keys(path, f"position {item.get('name')!r}", item, _POSITION_KEYS)
        pos = Position(
            name=_expect(path, "position name", item.get("name"), str),
            start=_expect(path, "position start", item.get("start"), int),
            end=_expect(path, "position end", item.get("end"), int),
        )
        if not (last_end < pos.start <= pos.end <= record_length):
            _fail(path, f"position {pos.name}: {pos.start}-{pos.end} overlaps or is out of range")
        last_end = pos.end
        positions.append(pos)
    return tuple(positions)


def parse_contract(data: Any, path: Any = "<contract>") -> Contract:
    """Validate a contract already loaded from YAML and build a ``Contract``."""
    _expect(path, "contract", data, dict)
    fmt = data.get("format")
    if fmt not in FORMATS:
        _fail(path, f"format must be one of {', '.join(FORMATS)}, got {fmt!r}")
    _check_keys(path, "contract", data, _FORMAT_KEYS[fmt])
    missing = sorted(_REQUIRED_KEYS - set(data))
    if missing:
        _fail(path, f"missing key(s): {', '.join(missing)}")

    _expect(path, "columns", data["columns"], list)
    columns = tuple(_parse_column(path, c) for c in data["columns"])
    names = [c.name for c in columns]
    if len(set(names)) != len(names):
        _fail(path, "duplicate column names")

    def ref(key: str, value: str) -> str:
        if value not in names:
            _fail(path, f"{key} refers to unknown column {value!r}")
        return value

    primary_key = _str_list(path, "primary_key", data["primary_key"])
    for k in primary_key:
        ref("primary_key", k)
        if not next(c for c in columns if c.name == k).required:
            _fail(path, f"primary key column {k} must be required")
    order_columns = _str_list(path, "order_columns", data.get("order_columns", []))
    for c in order_columns:
        ref("order_columns", c)
    optional_refs = {}
    for key in (
        "change_mode_column",
        "business_date_column",
        "control_qty_column",
        "control_qty_sign_column",
    ):
        value = data.get(key)
        if value is not None:
            optional_refs[key] = ref(key, _expect(path, key, value, str))

    landing_path = _expect(path, "landing_path", data["landing_path"], str)
    if re.sub(r"\{source_system\}", "", landing_path).count("{"):
        _fail(path, "landing_path only supports the {source_system} placeholder")
    if not landing_path.endswith("/"):
        _fail(path, "landing_path must end with /")

    kwargs: dict[str, Any] = {}
    if fmt == "csv":
        kwargs["delimiter"] = _expect(path, "delimiter", data.get("delimiter"), str)
        if len(kwargs["delimiter"]) != 1:
            _fail(path, "delimiter must be one character")
        kwargs["header"] = _expect(path, "header", data.get("header", True), bool)
    if fmt == "fixed_width":
        record_length = _expect(path, "record_length", data.get("record_length"), int)
        positions = _parse_positions(path, data.get("positions"), record_length)
        if [p.name for p in positions] != names:
            _fail(path, "positions must list exactly the columns, in the same order")
        kwargs.update(record_length=record_length, positions=positions, header=False)
    if fmt in ("csv", "fixed_width"):
        kwargs["encoding"] = _expect(path, "encoding", data.get("encoding", "utf-8"), str)
        if data.get("file_pattern") is not None:
            kwargs["file_pattern"] = _expect(path, "file_pattern", data["file_pattern"], str)
        control_file = _expect(path, "control_file", data.get("control_file", False), bool)
        if control_file and "control_qty_column" not in optional_refs:
            _fail(path, "control_file needs control_qty_column")
        kwargs["control_file"] = control_file

    source_system = data.get("source_system")
    if isinstance(source_system, str):
        source_system = [source_system]
    if "{source_system}" in landing_path and not source_system:
        _fail(path, "landing_path uses {source_system} but source_system is not set")

    return Contract(
        name=_expect(path, "name", data["name"], str),
        version=_expect(path, "version", data["version"], int),
        owner=_expect(path, "owner", data["owner"], str),
        description=data.get("description"),
        landing_path=landing_path,
        format=fmt,
        primary_key=primary_key,
        columns=columns,
        source_system=_str_list(path, "source_system", source_system or []),
        allow_empty=_expect(path, "allow_empty", data.get("allow_empty", False), bool),
        allow_new_columns=_expect(
            path, "allow_new_columns", data.get("allow_new_columns", False), bool
        ),
        order_columns=order_columns,
        arrival=data.get("arrival"),
        path=str(path),
        **optional_refs,
        **kwargs,
    )


def load_contract(path: str | Path) -> Contract:
    """Load and validate one contract YAML. Unknown keys or types raise ``ContractError``."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_contract(data, path)


def load_contracts(folder: str | Path) -> list[Contract]:
    """Load every ``*.yaml`` contract in a folder, sorted by file name."""
    contracts = [load_contract(p) for p in sorted(Path(folder).glob("*.yaml"))]
    names = [c.name for c in contracts]
    if len(set(names)) != len(names):
        raise ContractError(f"{folder}: duplicate contract names")
    return contracts
