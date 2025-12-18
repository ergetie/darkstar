import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import pytz

DB_PATH = "data/planner_learning.db"
TZ = pytz.timezone("Europe/Stockholm")


def fix_overlaps():
    print(f"Scanning {DB_PATH} for overlaps...")

    with sqlite3.connect(DB_PATH) as conn:
        query = "SELECT rowid, slot_start, slot_end FROM slot_observations ORDER BY slot_start"
        df = pd.read_sql_query(query, conn)

    if df.empty:
        print("Database is empty!")
        return

    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, format="mixed")
    df["slot_end"] = pd.to_datetime(df["slot_end"], utc=True, format="mixed")

    # Sort by start ASC, end DESC to handle duplicates (larger one comes first)
    df = df.sort_values(["slot_start", "slot_end"], ascending=[True, False]).reset_index(drop=True)

    overlaps = []
    modifications = []  # (rowid, new_end)
    deletions = []  # rowid

    # We iterate and check overlaps.
    # Since we might modify/delete, we need to be careful.
    # But we collect actions first.

    for i in range(len(df) - 1):
        curr = df.iloc[i]
        next_row = df.iloc[i + 1]

        # Check if current row was already marked for deletion (skip it?)
        # But we are iterating linearly. If A overlaps B, and we delete A, we don't care about A vs C.
        # But if we delete A, we should compare B vs C.
        # The loop does compare A vs B, then B vs C.
        # If we delete A, we effectively ignore it.
        # But if A overlaps B, and we delete A, we are done with A.

        if curr["rowid"] in deletions:
            continue

        if curr["slot_end"] > next_row["slot_start"]:
            # Overlap detected
            print(
                f"Overlap: Row {curr['rowid']} ({curr['slot_start']} - {curr['slot_end']}) overlaps with Row {next_row['rowid']} ({next_row['slot_start']})"
            )

            if curr["slot_start"] == next_row["slot_start"]:
                # Exact start match. Since we sorted end DESC, curr is the larger (or equal) one.
                # Delete curr.
                print(f"  Exact start match. Deleting larger/duplicate Row {curr['rowid']}")
                deletions.append(curr["rowid"])
            elif next_row["slot_start"] > curr["slot_start"]:
                # Partial overlap. Shrink curr.
                new_end = next_row["slot_start"]
                print(f"  Shrinking Row {curr['rowid']} to end at {new_end}")
                modifications.append((curr["rowid"], new_end))
            else:
                # Should not happen with sorted start
                print("  Warning: Unexpected sort order!")

    print(f"Found {len(modifications)} shrinks and {len(deletions)} deletions.")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if deletions:
            print("Applying deletions...")
            # Use parameter substitution
            placeholders = ",".join(["?"] * len(deletions))
            # Convert numpy ints to python ints
            deletions = [int(x) for x in deletions]
            sql = f"DELETE FROM slot_observations WHERE rowid IN ({placeholders})"
            cursor.execute(sql, deletions)
            print(f"Deleted {cursor.rowcount} rows.")

        if modifications:
            print("Applying shrinks...")
            for rowid, new_end in modifications:
                new_end_iso = new_end.isoformat()
                cursor.execute(
                    "UPDATE slot_observations SET slot_end = ? WHERE rowid = ?",
                    (new_end_iso, rowid),
                )
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    fix_overlaps()
