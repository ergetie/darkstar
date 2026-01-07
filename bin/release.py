#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys


def sh(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def get_current_branch():
    res = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return res.stdout.strip()


def get_last_tag():
    try:
        res = sh(["git", "describe", "--tags", "--abbrev=0"])
        return res.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def bump(tag: str, kind: str) -> str:
    m = SEMVER_RE.match(tag or "")
    if not m:
        # default starting point
        major, minor, patch = 0, 13, 0
    else:
        major, minor, patch = map(int, m.groups())
    if kind == "major":
        major += 1
        minor = 0
        patch = 0
    elif kind == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f"v{major}.{minor}.{patch}"


def ensure_clean_or_commit(message: str):
    res = sh(["git", "status", "--porcelain"], check=False)
    if res.stdout.strip():
        sh(["git", "add", "-A"])  # stage everything
        sh(["git", "commit", "-m", message or "chore: release prep"])


def main():
    ap = argparse.ArgumentParser(description="Create a tagged release and push")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bump", choices=["patch", "minor", "major"], help="bump type")
    g.add_argument("--version", help="explicit version like v0.13.2")
    ap.add_argument("-m", "--message", default="release", help="tag/commit message")
    args = ap.parse_args()

    # Sync with origin
    sh(["git", "fetch", "--all"])  # get latest refs

    branch = get_current_branch()
    if branch != "main":
        print(f"ERROR: not on main (current: {branch})", file=sys.stderr)
        return 2

    # Rebase onto latest origin/main
    sh(["git", "pull", "--rebase", "origin", "main"])  # may be no-op

    ensure_clean_or_commit(args.message)

    # Decide version
    if args.version:
        new_version = args.version if args.version.startswith("v") else f"v{args.version}"
    else:
        last = get_last_tag()
        new_version = bump(last or "v0.13.0", args.bump or "patch")

    # Create tag
    sh(["git", "tag", "-a", new_version, "-m", f"{new_version}: {args.message}"])

    # Push branch and tags
    sh(["git", "push", "origin", "main"])
    sh(["git", "push", "--tags"])

    print(f"\nDone. Created and pushed {new_version}.")
    print("On the server (LXC):")
    print("  cd /opt/darkstar && git fetch --all && git reset --hard origin/main")
    print("  source venv/bin/activate && pip install -r requirements.txt")
    print("  uvicorn backend.main:app --host 0.0.0.0 --port 5000")


if __name__ == "__main__":
    sys.exit(main())
