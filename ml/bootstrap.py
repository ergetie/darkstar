import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


# Files of the removed error-correction models; unused, but they would still show up in the
# training status listing and could be restored from a backup.
STALE_MODEL_FILES = ("pv_error.lgb", "load_error.lgb")


def purge_stale_error_models(runtime_dir: Path) -> list[Path]:
    """Delete the stale `*_error.lgb` files from the runtime models directory, its
    `defaults/` copy and every training backup folder. Idempotent; returns what was deleted."""
    folders = [runtime_dir, runtime_dir / "defaults"]
    backup_dir = runtime_dir / "backup"
    if backup_dir.is_dir():
        folders.extend(sorted(p for p in backup_dir.iterdir() if p.is_dir()))
    deleted: list[Path] = []
    for folder in folders:
        for name in STALE_MODEL_FILES:
            path = folder / name
            try:
                existed = path.exists()
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not delete stale model file %s: %s", path, exc)
                continue
            if existed:
                logger.info("Deleted stale model file %s", path)
                deleted.append(path)
    return deleted


def ensure_active_models():
    """
    Implements 'Seed & Drift' strategy for ML models.

    1. Checks if runtime models exist in `data/ml/models/`.
    2. If EMPTY: Copies from `ml/models/defaults/` (Seeding).
    3. If EXISTS: Does nothing (Drift/Training preserved).
    4. ALWAYS: Copies defaults to `data/ml/models/defaults/` for reference/reset.
    5. ALWAYS: Deletes the stale `pv_error.lgb` / `load_error.lgb` files first.
    """
    # Use relative paths anchored to this file for robustness across Docker/Local
    base_dir = Path(__file__).parent.parent  # Project root
    defaults_dir = base_dir / "ml" / "models" / "defaults"
    runtime_dir = base_dir / "data" / "ml" / "models"
    runtime_defaults_dir = runtime_dir / "defaults"

    logger.info(f"Model Bootstrap: Checking {runtime_dir}")

    # Purge the stale error-correction models first, so a missing defaults folder cannot skip it
    purge_stale_error_models(runtime_dir)

    # Safety check: Defaults must exist
    if not defaults_dir.exists():
        logger.error(f"CRITICAL: Default models missing at {defaults_dir}")
        return

    # Ensure runtime directory exists
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # 1. Seed if empty
    # Filter for .lgb files to avoid counting directories or temp files
    existing_models = list(runtime_dir.glob("*.lgb"))

    if not existing_models:
        logger.info("⚠️ No active models found. Seeding from defaults...")
        for model_file in defaults_dir.glob("*.lgb"):
            shutil.copy2(model_file, runtime_dir / model_file.name)
        logger.info("✅ Seeding complete.")
    else:
        logger.info(f"✅ Active models found ({len(existing_models)} files). Skipping seed.")

    # 2. Always update the "Factory Reset" image in data/
    # This allows users to see what the defaults are without digging into source code
    if runtime_defaults_dir.exists():
        shutil.rmtree(runtime_defaults_dir)
    shutil.copytree(defaults_dir, runtime_defaults_dir)
    logger.info("Updated runtime defaults backup.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_active_models()
