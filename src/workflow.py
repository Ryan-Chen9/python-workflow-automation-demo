"""Clean and summarize synthetic order data from JSON or CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, TypeVar


CENT = Decimal("0.01")
T = TypeVar("T")

DEFAULT_CONFIG: dict[str, Any] = {
    "accepted_statuses": [
        "pending",
        "paid",
        "shipped",
        "completed",
        "refunded",
        "cancelled",
    ],
    "revenue_statuses": ["paid", "shipped", "completed"],
    "currency": "USD",
    "duplicate_policy": "keep_last",
    "max_read_attempts": 3,
    "retry_delay_seconds": 0.05,
}


class DataValidationError(ValueError):
    """Raised when an input record does not meet the workflow contract."""


def retry_call(
    operation: Callable[[], T],
    *,
    attempts: int,
    delay_seconds: float,
    retry_on: tuple[type[BaseException], ...] = (OSError,),
    logger: logging.Logger | None = None,
) -> T:
    """Call an operation again after retryable failures.

    The helper is intentionally generic so a real project can wrap a local
    file, database, or authorized API operation without changing the workflow.
    """

    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")

    log = logger or logging.getLogger(__name__)
    for attempt_number in range(1, attempts + 1):
        try:
            return operation()
        except retry_on as exc:
            if attempt_number == attempts:
                log.error("Operation failed after %d attempt(s): %s", attempts, exc)
                raise
            log.warning(
                "Attempt %d/%d failed (%s); retrying in %.2f seconds",
                attempt_number,
                attempts,
                exc,
                delay_seconds,
            )
            if delay_seconds:
                time.sleep(delay_seconds)

    raise RuntimeError("retry loop ended unexpectedly")


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and validate workflow configuration."""

    config = dict(DEFAULT_CONFIG)
    if path is not None:
        with path.open("r", encoding="utf-8") as handle:
            supplied = json.load(handle)
        if not isinstance(supplied, dict):
            raise ValueError("configuration must be a JSON object")
        config.update(supplied)

    accepted = config.get("accepted_statuses")
    revenue = config.get("revenue_statuses")
    if not isinstance(accepted, list) or not accepted:
        raise ValueError("accepted_statuses must be a non-empty list")
    if not isinstance(revenue, list):
        raise ValueError("revenue_statuses must be a list")

    accepted_set = {str(value).strip().lower() for value in accepted}
    revenue_set = {str(value).strip().lower() for value in revenue}
    if not revenue_set.issubset(accepted_set):
        raise ValueError("revenue_statuses must be included in accepted_statuses")

    duplicate_policy = config.get("duplicate_policy")
    if duplicate_policy not in {"keep_first", "keep_last"}:
        raise ValueError("duplicate_policy must be keep_first or keep_last")

    max_attempts = config.get("max_read_attempts")
    delay = config.get("retry_delay_seconds")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_read_attempts must be a positive integer")
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
        raise ValueError("retry_delay_seconds must be a non-negative number")

    currency = str(config.get("currency", "")).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter code")

    config["accepted_statuses"] = sorted(accepted_set)
    config["revenue_statuses"] = sorted(revenue_set)
    config["currency"] = currency
    config["retry_delay_seconds"] = float(delay)
    return config


def _read_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("orders")
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("JSON input must be a list of objects or an object with an orders list")
    return payload


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_orders(
    path: Path,
    *,
    attempts: int = 3,
    delay_seconds: float = 0.05,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Read order records from a supported local file with retry handling."""

    suffix = path.suffix.lower()
    if suffix == ".json":
        reader = lambda: _read_json(path)
    elif suffix == ".csv":
        reader = lambda: _read_csv(path)
    else:
        raise ValueError("input file must use .json or .csv")

    return retry_call(
        reader,
        attempts=attempts,
        delay_seconds=delay_seconds,
        retry_on=(OSError,),
        logger=logger,
    )


def _required_text(raw: Mapping[str, Any], field: str) -> str:
    value = str(raw.get(field, "")).strip()
    if not value:
        raise DataValidationError(f"{field} is required")
    return value


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise DataValidationError(f"{field} must be a positive whole number")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise DataValidationError(f"{field} must be a positive whole number") from None
    if parsed != parsed.to_integral_value() or parsed <= 0:
        raise DataValidationError(f"{field} must be a positive whole number")
    return int(parsed)


def _non_negative_money(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise DataValidationError(f"{field} must be a non-negative amount")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise DataValidationError(f"{field} must be a non-negative amount") from None
    if not parsed.is_finite() or parsed < 0:
        raise DataValidationError(f"{field} must be a non-negative amount")
    return parsed.quantize(CENT, rounding=ROUND_HALF_UP)


def clean_order(raw: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one order record."""

    order_id = _required_text(raw, "order_id")
    customer = _required_text(raw, "customer")
    product = _required_text(raw, "product")
    quantity = _positive_integer(raw.get("quantity"), "quantity")
    unit_price = _non_negative_money(raw.get("unit_price"), "unit_price")

    status = _required_text(raw, "status").lower()
    if status not in config["accepted_statuses"]:
        allowed = ", ".join(config["accepted_statuses"])
        raise DataValidationError(f"status must be one of: {allowed}")

    raw_date = _required_text(raw, "order_date")
    try:
        order_date = date.fromisoformat(raw_date).isoformat()
    except ValueError:
        raise DataValidationError("order_date must use YYYY-MM-DD") from None

    country = _required_text(raw, "country").upper()
    if len(country) != 2 or not country.isalpha():
        raise DataValidationError("country must be a two-letter code")

    line_total = (unit_price * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "order_id": order_id,
        "customer": customer,
        "product": product,
        "quantity": quantity,
        "unit_price": f"{unit_price:.2f}",
        "currency": config["currency"],
        "status": status,
        "order_date": order_date,
        "country": country,
        "line_total": f"{line_total:.2f}",
    }


def clean_orders(
    records: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Clean records, report rejected rows, and resolve duplicate order IDs."""

    log = logger or logging.getLogger(__name__)
    accepted_by_id: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []

    for index, raw in enumerate(records, start=1):
        try:
            cleaned = clean_order(raw, config)
        except DataValidationError as exc:
            rejected.append(
                {
                    "record_number": index,
                    "order_id": str(raw.get("order_id", "")).strip() or None,
                    "reason": str(exc),
                }
            )
            log.warning("Rejected record %d: %s", index, exc)
            continue

        order_id = cleaned["order_id"]
        if order_id in accepted_by_id:
            policy = config["duplicate_policy"]
            log.warning("Duplicate order_id %s encountered; policy=%s", order_id, policy)
            if policy == "keep_first":
                continue
        accepted_by_id[order_id] = cleaned

    return list(accepted_by_id.values()), rejected


def aggregate_orders(
    orders: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> dict[str, Any]:
    """Build deterministic order and revenue summaries."""

    by_status: dict[str, dict[str, Any]] = {}
    by_country: dict[str, dict[str, Any]] = {}
    recognized_revenue = Decimal("0.00")
    gross_value = Decimal("0.00")

    for order in orders:
        amount = Decimal(str(order["line_total"]))
        status = str(order["status"])
        country = str(order["country"])
        gross_value += amount
        if status in config["revenue_statuses"]:
            recognized_revenue += amount

        status_bucket = by_status.setdefault(
            status, {"order_count": 0, "gross_value": Decimal("0.00")}
        )
        status_bucket["order_count"] += 1
        status_bucket["gross_value"] += amount

        country_bucket = by_country.setdefault(
            country, {"order_count": 0, "gross_value": Decimal("0.00")}
        )
        country_bucket["order_count"] += 1
        country_bucket["gross_value"] += amount

    def serialize_buckets(buckets: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        return {
            key: {
                "order_count": value["order_count"],
                "gross_value": f"{value['gross_value'].quantize(CENT):.2f}",
            }
            for key, value in sorted(buckets.items())
        }

    return {
        "currency": config["currency"],
        "order_count": len(orders),
        "gross_value": f"{gross_value.quantize(CENT):.2f}",
        "recognized_revenue": f"{recognized_revenue.quantize(CENT):.2f}",
        "revenue_statuses": list(config["revenue_statuses"]),
        "by_status": serialize_buckets(by_status),
        "by_country": serialize_buckets(by_country),
    }


def write_outputs(
    output_dir: Path,
    orders: Sequence[Mapping[str, Any]],
    rejected: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> dict[str, Path]:
    """Write cleaned CSV, summary JSON, and rejection JSON files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "cleaned_orders.csv"
    summary_path = output_dir / "summary.json"
    rejected_path = output_dir / "rejected_orders.json"

    fields = [
        "order_id",
        "customer",
        "product",
        "quantity",
        "unit_price",
        "currency",
        "status",
        "order_date",
        "country",
        "line_total",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(orders)

    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")

    with rejected_path.open("w", encoding="utf-8") as handle:
        json.dump(list(rejected), handle, indent=2, sort_keys=True)
        handle.write("\n")

    return {
        "cleaned_csv": csv_path,
        "summary_json": summary_path,
        "rejected_json": rejected_path,
    }


def configure_logging(log_path: Path) -> logging.Logger:
    """Create isolated console and file logging for one run."""

    logger = logging.getLogger("workflow_demo")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger


def run_workflow(input_path: Path, output_dir: Path, config_path: Path | None) -> dict[str, Any]:
    """Execute the complete local workflow and return a run manifest."""

    output_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(output_dir / "workflow.log")
    config = load_config(config_path)
    logger.info("Reading synthetic input from %s", input_path)
    records = load_orders(
        input_path,
        attempts=config["max_read_attempts"],
        delay_seconds=config["retry_delay_seconds"],
        logger=logger,
    )
    logger.info("Loaded %d raw record(s)", len(records))

    cleaned, rejected = clean_orders(records, config, logger=logger)
    summary = aggregate_orders(cleaned, config)
    paths = write_outputs(output_dir, cleaned, rejected, summary)
    logger.info("Accepted %d record(s); rejected %d", len(cleaned), len(rejected))
    logger.info("Wrote outputs to %s", output_dir)
    return {
        "raw_count": len(records),
        "cleaned_count": len(cleaned),
        "rejected_count": len(rejected),
        "summary": summary,
        "paths": paths,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean and summarize local synthetic order JSON or CSV data."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input .json or .csv file")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output directory")
    parser.add_argument("--config", type=Path, help="Optional JSON configuration")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = run_workflow(args.input, args.output_dir, args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logging.getLogger("workflow_demo").error("Workflow failed: %s", exc)
        return 1

    print(
        json.dumps(
            {
                "raw_count": manifest["raw_count"],
                "cleaned_count": manifest["cleaned_count"],
                "rejected_count": manifest["rejected_count"],
                "summary": manifest["summary"],
                "outputs": {key: str(value) for key, value in manifest["paths"].items()},
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
