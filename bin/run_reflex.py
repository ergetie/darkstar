#!/usr/bin/env python3
import argparse
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from backend.learning.reflex import AuroraReflex

def main():
    parser = argparse.ArgumentParser(description="Aurora Reflex: Long-Term Auto-Tuner")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying them")
    parser.add_argument("--force", action="store_true", help="Run even if disabled in config")
    args = parser.parse_args()

    print(f"Starting Aurora Reflex (Dry Run: {args.dry_run})...")
    
    try:
        reflex = AuroraReflex()
        
        # Check if enabled (unless forced)
        if not args.force and not reflex.config.get("learning", {}).get("reflex_enabled", False):
            print("Aurora Reflex is disabled in config. Use --force to override.")
            return

        report = reflex.run(dry_run=args.dry_run)
        
        print("\n--- Report ---")
        for line in report:
            print(f"- {line}")
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
