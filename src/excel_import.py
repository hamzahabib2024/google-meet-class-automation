"""
excel_import.py

Imports the batch list from an Excel file. Since students are already
handled via calendar guests (no code needed for that), this only needs
three columns, one row per batch:

    Batch Name   -> e.g. "Section A - Graphic Design"
    Subject      -> e.g. "Graphic Design"
    Meet Link    -> e.g. "https://meet.google.com/abc-defg-hij"

Usage:
    from src.excel_import import import_batches_from_excel
    import_batches_from_excel("path/to/batches.xlsx")
"""

import logging
from typing import Dict

import pandas as pd

from src.db import get_session, Batch

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "batchname": "batch_name",
    "subject": "subject",
    "meetlink": "meet_link",
}


def _normalize_column_name(name: str) -> str:
    return str(name).strip().lower().replace(" ", "").replace("_", "")


def _load_and_validate(excel_path: str) -> pd.DataFrame:
    df = pd.read_excel(excel_path)
    normalized_to_actual = {_normalize_column_name(c): c for c in df.columns}

    missing = [
        canonical for norm, canonical in REQUIRED_COLUMNS.items()
        if norm not in normalized_to_actual
    ]
    if missing:
        raise ValueError(
            f"Excel file '{excel_path}' is missing required column(s): {missing}. "
            f"Found columns: {list(df.columns)}."
        )

    rename_map = {normalized_to_actual[norm]: canonical for norm, canonical in REQUIRED_COLUMNS.items()}
    df = df.rename(columns=rename_map)
    df = df.dropna(how="all")

    required_cols = list(REQUIRED_COLUMNS.values())

    # Check for real NaN values *before* casting to str. astype(str) turns a
    # missing cell into the literal string "nan", which would otherwise slip
    # past a blank_mask check that only looks for "".
    nan_mask = df[required_cols].isna().any(axis=1)
    if nan_mask.any():
        bad_rows = df[nan_mask].index.tolist()
        raise ValueError(f"Excel file has blank required values in row(s): {bad_rows}.")

    for col in required_cols:
        df[col] = df[col].astype(str).str.strip()

    # Belt-and-suspenders: also catch whitespace-only cells and the literal
    # text "nan" in case a cell contained that string to begin with.
    blank_mask = df[required_cols].apply(
        lambda col: col.str.lower().isin(["", "nan", "none"])
    ).any(axis=1)
    if blank_mask.any():
        bad_rows = df[blank_mask].index.tolist()
        raise ValueError(f"Excel file has blank required values in row(s): {bad_rows}.")

    return df


def import_batches_from_excel(excel_path: str) -> Dict[str, int]:
    """Upserts batches into the database. Returns a summary dict."""
    df = _load_and_validate(excel_path)
    summary = {"batches_created": 0, "batches_updated": 0}

    with get_session() as session:
        for _, row in df.iterrows():
            # Batch name is the destination folder name, not the unique Meet
            # source. Use Meet link as the import identity so duplicate names
            # do not overwrite each other.
            batch = session.query(Batch).filter_by(meet_link=row["meet_link"]).one_or_none()
            if batch is None:
                session.add(Batch(
                    section_name=row["batch_name"],
                    subject=row["subject"],
                    meet_link=row["meet_link"],
                ))
                summary["batches_created"] += 1
                logger.info("Created new batch: %s", row["batch_name"])
            else:
                batch.subject = row["subject"]
                batch.meet_link = row["meet_link"]
                summary["batches_updated"] += 1
                logger.info("Updated existing Meet source for batch: %s", row["batch_name"])

    logger.info("Import complete: %s", summary)
    return summary
