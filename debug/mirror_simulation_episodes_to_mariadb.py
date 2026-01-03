import json
import sqlite3
from typing import Any

from learning import LearningEngine


def main() -> None:
    engine = LearningEngine()
    db_path = engine.db_path
    print(f"[mirror] Using SQLite: {db_path}")

    conn = sqlite3.connect(db_path, timeout=30.0)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT episode_id, inputs_json, context_json, schedule_json, config_overrides_json
        FROM training_episodes
        WHERE context_json LIKE '%"system_id": "simulation"%'
        """
    )
    rows = cur.fetchall()
    print(f"[mirror] Simulation episodes to mirror: {len(rows)}")

    for idx, (
        episode_id,
        inputs_json,
        context_json,
        schedule_json,
        overrides_json,
    ) in enumerate(rows, 1):
        system_id: str = "simulation"
        if context_json:
            try:
                ctx: dict[str, Any] = json.loads(context_json)
                system_id = str(ctx.get("system_id") or system_id)
            except Exception:
                system_id = "simulation"

        engine._mirror_episode_to_mariadb(
            episode_id=episode_id,
            inputs_json=inputs_json,
            context_json=context_json,
            schedule_json=schedule_json,
            overrides_json=overrides_json,
            system_id=system_id,
        )
        if idx % 1000 == 0:
            print(f"[mirror] Mirrored {idx} episodes...")

    conn.close()
    print("[mirror] Done.")


if __name__ == "__main__":
    main()
