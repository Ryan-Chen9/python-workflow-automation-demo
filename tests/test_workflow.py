import csv
import json
import logging
import tempfile
import unittest
from pathlib import Path

from src.workflow import (
    aggregate_orders,
    clean_orders,
    load_config,
    load_orders,
    retry_call,
    run_workflow,
)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_cleaning_deduplication_rejections_and_aggregation(self):
        records = [
            {
                "order_id": " A-1 ",
                "customer": " Example Buyer ",
                "product": "Widget",
                "quantity": "2",
                "unit_price": "12.345",
                "status": " PAID ",
                "order_date": "2026-08-01",
                "country": "us",
            },
            {
                "order_id": "A-1",
                "customer": "Example Buyer",
                "product": "Widget",
                "quantity": 1,
                "unit_price": "10.00",
                "status": "completed",
                "order_date": "2026-08-02",
                "country": "US",
            },
            {
                "order_id": "A-2",
                "customer": "Bad Quantity Demo",
                "product": "Widget",
                "quantity": 0,
                "unit_price": "3.00",
                "status": "pending",
                "order_date": "2026-08-03",
                "country": "CA",
            },
        ]

        cleaned, rejected = clean_orders(records, self.config)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["order_id"], "A-1")
        self.assertEqual(cleaned[0]["status"], "completed")
        self.assertEqual(cleaned[0]["line_total"], "10.00")
        self.assertEqual(len(rejected), 1)
        self.assertIn("positive whole number", rejected[0]["reason"])

        summary = aggregate_orders(cleaned, self.config)
        self.assertEqual(summary["order_count"], 1)
        self.assertEqual(summary["gross_value"], "10.00")
        self.assertEqual(summary["recognized_revenue"], "10.00")
        self.assertEqual(summary["by_country"]["US"]["order_count"], 1)

    def test_loads_json_and_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            json_path = root / "orders.json"
            csv_path = root / "orders.csv"
            json_path.write_text(json.dumps({"orders": [{"order_id": "J-1"}]}), encoding="utf-8")
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["order_id"])
                writer.writeheader()
                writer.writerow({"order_id": "C-1"})

            self.assertEqual(load_orders(json_path)[0]["order_id"], "J-1")
            self.assertEqual(load_orders(csv_path)[0]["order_id"], "C-1")

    def test_retry_call_recovers_from_transient_oserror(self):
        attempts = {"count": 0}

        def sometimes_fails():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OSError("synthetic temporary failure")
            return "ok"

        result = retry_call(
            sometimes_fails,
            attempts=3,
            delay_seconds=0,
            logger=logging.getLogger("retry_test"),
        )
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)

    def test_complete_workflow_writes_auditable_outputs(self):
        records = {
            "orders": [
                {
                    "order_id": "RUN-1",
                    "customer": "Synthetic Buyer",
                    "product": "Demo Item",
                    "quantity": 2,
                    "unit_price": "4.25",
                    "status": "paid",
                    "order_date": "2026-08-09",
                    "country": "jp",
                },
                {
                    "order_id": "RUN-2",
                    "customer": "Synthetic Buyer",
                    "product": "Demo Item",
                    "quantity": -1,
                    "unit_price": "4.25",
                    "status": "paid",
                    "order_date": "2026-08-09",
                    "country": "jp",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            output_dir = root / "output"
            input_path.write_text(json.dumps(records), encoding="utf-8")

            manifest = run_workflow(input_path, output_dir, None)

            self.assertEqual(manifest["raw_count"], 2)
            self.assertEqual(manifest["cleaned_count"], 1)
            self.assertEqual(manifest["rejected_count"], 1)
            self.assertTrue((output_dir / "cleaned_orders.csv").is_file())
            self.assertTrue((output_dir / "summary.json").is_file())
            self.assertTrue((output_dir / "rejected_orders.json").is_file())
            self.assertTrue((output_dir / "workflow.log").is_file())

            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["recognized_revenue"], "8.50")


if __name__ == "__main__":
    unittest.main()
