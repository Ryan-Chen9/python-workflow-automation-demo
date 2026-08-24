# Python CSV/JSON Workflow Automation — Validation, Logging & Reports

[![CI](https://github.com/Ryan-Chen9/python-workflow-automation-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/Ryan-Chen9/python-workflow-automation-demo/actions/workflows/ci.yml)

![Python CSV and JSON workflow automation demo](assets/hero-v2.png)

This repository is a **synthetic demonstration**, created from fictional order data. It is not a client project and contains no customer code, credentials, or private data.

**Proof first:** [Inspect example outputs](#example-outputs) · [Run the demo](#run-the-json-example) · [View all demos](https://github.com/Ryan-Chen9) · **[Request a tailored Python workflow on Fiverr →](https://www.fiverr.com/ryan_chen09/write-a-python-script-web-scraper-or-automation-tool-for-you)**

The demo shows a small but production-minded local workflow:

1. Read order records from JSON or CSV.
2. Retry transient file-read failures and write an audit log.
3. Normalize text, dates, quantities, money, statuses, and country codes.
4. Reject invalid rows with an explicit reason and de-duplicate order IDs.
5. Write cleaned CSV data plus JSON summaries and rejection details.

Everything runs locally with the Python standard library. The workflow makes no network requests.

## Example outputs

Running the demo creates:

- `cleaned_orders.csv` — validated, normalized order rows
- `summary.json` — order and revenue totals by status and country
- `rejected_orders.json` — invalid rows and their validation errors
- `workflow.log` — processing, retry, duplicate, and output events

Committed sample artifacts:

- [JSON-input cleaned CSV](sample_output/json-demo/cleaned_orders.csv)
- [JSON-input summary](sample_output/json-demo/summary.json)
- [CSV-input cleaned CSV](sample_output/csv-demo/cleaned_orders.csv)
- [CSV-input summary](sample_output/csv-demo/summary.json)

## Verified sample result

| Input | Raw | Cleaned | Rejected | Recognized revenue |
| --- | ---: | ---: | ---: | ---: |
| JSON | 4 | 3 | 1 | USD 155.15 |
| CSV | 4 | 3 | 1 | USD 69.49 |

## Requirements

- Python 3.10 or newer
- No third-party packages

## Run the JSON example

```bash
python3 -m src.workflow \
  --input data/orders.json \
  --config config.example.json \
  --output-dir output/json-demo
```

## Run the CSV example

```bash
python3 -m src.workflow \
  --input data/orders.csv \
  --config config.example.json \
  --output-dir output/csv-demo
```

## Run the tests

```bash
python3 -m unittest discover -s tests -v
```

The tests cover JSON and CSV loading, normalization, aggregation, duplicate handling, rejected-row reporting, output generation, and retry behavior.

## Configuration

Copy or edit `config.example.json` to control:

- accepted order statuses
- which statuses count toward recognized revenue
- output currency
- duplicate-record policy (`keep_first` or `keep_last`)
- read retry attempts and delay

The currency setting labels the output; it does not perform currency conversion. All inputs for one run must already use the same currency.

## Data contract

Each input record must provide:

| Field | Expected value |
| --- | --- |
| `order_id` | non-empty unique identifier |
| `customer` | non-empty text |
| `product` | non-empty text |
| `quantity` | positive whole number |
| `unit_price` | non-negative decimal amount |
| `status` | a configured status |
| `order_date` | ISO date (`YYYY-MM-DD`) |
| `country` | two-letter country code |

## Want a workflow adapted to your files?

I build scoped local Python automation for authorized CSV and JSON file processing, validation, and reporting. See the related Fiverr service:

**[View my Python automation service on Fiverr](https://www.fiverr.com/ryan_chen09/write-a-python-script-web-scraper-or-automation-tool-for-you)**

Please share representative sample input, the required output, approximate volume, environment, deadline, and acceptance criteria before ordering.

## License

MIT — see [LICENSE](LICENSE).
