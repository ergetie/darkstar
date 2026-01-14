#!/usr/bin/env python3
"""
Helper script to inspect training_episodes with compressed JSON.

Usage:
    # List all episodes
    python bin/inspect_episodes.py list

    # Show specific episode (decompressed)
    python bin/inspect_episodes.py show <episode_id>

    # Search episodes by date
    python bin/inspect_episodes.py search --date 2025-11-28

    # Export episode as readable JSON file
    python bin/inspect_episodes.py export <episode_id> --output episode.json
"""

import argparse
import json
import sqlite3
import sys
import zlib
from pathlib import Path


def get_db_path() -> Path:
    """Get the database path from config."""
    try:
        from inputs import load_yaml
        config = load_yaml("config.yaml")
        return Path(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
    except Exception:
        return Path("data/planner_learning.db")


def decompress_if_needed(data: bytes | str) -> str:
    """Try to decompress data, fallback to plain text if not compressed."""
    if isinstance(data, str):
        return data

    try:
        # Try zlib decompression
        return zlib.decompress(data).decode('utf-8')
    except (zlib.error, UnicodeDecodeError):
        # Not compressed, treat as plain text
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return str(data)


def list_episodes(conn: sqlite3.Connection, limit: int = 50) -> None:
    """List recent episodes with basic info."""
    cursor = conn.execute(
        """
        SELECT episode_id, created_at,
               LENGTH(inputs_json) as inputs_size,
               LENGTH(schedule_json) as schedule_size
        FROM training_episodes
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,)
    )

    print(f"{'Episode ID':<40} {'Created At':<20} {'Inputs':<10} {'Schedule':<10}")
    print("-" * 85)
    for row in cursor:
        episode_id, created_at, inputs_size, schedule_size = row
        # Format sizes
        def fmt_size(b):
            if b < 1024:
                return f"{b}B"
            elif b < 1024*1024:
                return f"{b/1024:.1f}KB"
            else:
                return f"{b/1024/1024:.1f}MB"

        print(f"{episode_id:<40} {created_at:<20} {fmt_size(inputs_size):<10} {fmt_size(schedule_size):<10}")


def show_episode(conn: sqlite3.Connection, episode_id: str) -> None:
    """Show full episode content (decompressed)."""
    cursor = conn.execute(
        "SELECT inputs_json, schedule_json, context_json FROM training_episodes WHERE episode_id = ?",
        (episode_id,)
    )
    row = cursor.fetchone()

    if not row:
        print(f"Episode '{episode_id}' not found", file=sys.stderr)
        sys.exit(1)

    inputs_raw, schedule_raw, context_raw = row

    print("=" * 80)
    print(f"EPISODE: {episode_id}")
    print("=" * 80)

    # Decompress and pretty-print
    print("\n--- INPUTS ---")
    inputs = json.loads(decompress_if_needed(inputs_raw))
    print(json.dumps(inputs, indent=2))

    print("\n--- SCHEDULE (first 3 slots) ---")
    schedule = json.loads(decompress_if_needed(schedule_raw))
    schedule_preview = dict(schedule)
    if "schedule" in schedule_preview and len(schedule_preview["schedule"]) > 3:
        schedule_preview["schedule"] = schedule_preview["schedule"][:3]
        schedule_preview["_truncated"] = f"{len(schedule['schedule']) - 3} more slots..."
    print(json.dumps(schedule_preview, indent=2))

    if context_raw:
        print("\n--- CONTEXT ---")
        context = json.loads(decompress_if_needed(context_raw))
        print(json.dumps(context, indent=2))


def search_episodes(conn: sqlite3.Connection, date: str | None = None) -> None:
    """Search episodes by filters."""
    if date:
        # Search via context_json LIKE (works if context not compressed)
        cursor = conn.execute(
            """
            SELECT episode_id, created_at
            FROM training_episodes
            WHERE created_at LIKE ? OR episode_id LIKE ?
            ORDER BY created_at DESC
            """,
            (f"%{date}%", f"%{date}%")
        )

        results = cursor.fetchall()
        if not results:
            print(f"No episodes found matching '{date}'")
            return

        print(f"Found {len(results)} episodes:")
        for episode_id, created_at in results:
            print(f"  {episode_id} ({created_at})")


def export_episode(conn: sqlite3.Connection, episode_id: str, output_path: str) -> None:
    """Export episode to JSON file."""
    cursor = conn.execute(
        "SELECT inputs_json, schedule_json, context_json, config_overrides_json FROM training_episodes WHERE episode_id = ?",
        (episode_id,)
    )
    row = cursor.fetchone()

    if not row:
        print(f"Episode '{episode_id}' not found", file=sys.stderr)
        sys.exit(1)

    inputs_raw, schedule_raw, context_raw, overrides_raw = row

    # Decompress all fields
    export_data = {
        "episode_id": episode_id,
        "inputs": json.loads(decompress_if_needed(inputs_raw)),
        "schedule": json.loads(decompress_if_needed(schedule_raw)),
        "context": json.loads(decompress_if_needed(context_raw)) if context_raw else None,
        "config_overrides": json.loads(decompress_if_needed(overrides_raw)) if overrides_raw else None,
    }

    with Path(output_path).open('w') as f:
        json.dump(export_data, f, indent=2)

    print(f"Episode exported to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Inspect training episodes (handles compressed data)")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    list_parser = subparsers.add_parser("list", help="List recent episodes")
    list_parser.add_argument("--limit", type=int, default=50, help="Max episodes to show")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show full episode content")
    show_parser.add_argument("episode_id", help="Episode ID to show")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search episodes")
    search_parser.add_argument("--date", help="Search by date (YYYY-MM-DD)")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export episode to JSON file")
    export_parser.add_argument("episode_id", help="Episode ID to export")
    export_parser.add_argument("--output", default="episode.json", help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Connect to database
    db_path = get_db_path()
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    with sqlite3.connect(str(db_path)) as conn:
        if args.command == "list":
            list_episodes(conn, args.limit)
        elif args.command == "show":
            show_episode(conn, args.episode_id)
        elif args.command == "search":
            search_episodes(conn, args.date)
        elif args.command == "export":
            export_episode(conn, args.episode_id, args.output)


if __name__ == "__main__":
    main()
