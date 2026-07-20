"""
scripts/add_batch.py

CLI to import/update the batch list from an Excel file.

Usage:
    python -m scripts.add_batch path/to/batches.xlsx

Expected Excel columns (one row per batch): Batch Name, Subject, Meet Link.
"""

import argparse
import sys

from src.logging_setup import setup_logging
from src.db import init_db
from src.excel_import import import_batches_from_excel


def main() -> None:
    parser = argparse.ArgumentParser(description="Import batches from an Excel file.")
    parser.add_argument("excel_path", help="Path to the .xlsx file to import.")
    args = parser.parse_args()

    setup_logging()
    init_db()

    print(f"Importing batches from: {args.excel_path}")
    try:
        summary = import_batches_from_excel(args.excel_path)
    except ValueError as exc:
        print(f"\nImport failed — problem with the Excel file:\n  {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nImport failed — unexpected error:\n  {exc}")
        sys.exit(1)

    print(
        f"\nImport complete:\n"
        f"  Batches created: {summary['batches_created']}\n"
        f"  Batches updated: {summary['batches_updated']}\n"
    )


if __name__ == "__main__":
    main()
