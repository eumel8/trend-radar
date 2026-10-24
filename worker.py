"""Cluster worker: serialized collection/publication and weekly private upload."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import tomllib

import radar
import editor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["collect", "refresh", "video"])
    args = parser.parse_args()
    runtime = Path(os.environ.get("RADAR_RUNTIME", "/data/runtime"))
    runtime.mkdir(parents=True, exist_ok=True)
    config = tomllib.loads(Path("/app/config.toml").read_text())
    # Shared lock covers manual jobs and different CronJobs, not just one schedule.
    with (runtime / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db = radar.database(runtime)
        try:
            if args.action in {"collect", "refresh"}:
                radar.collect(db, config, discover=args.action == "collect")
                public = Path("/data/public")
                public.mkdir(exist_ok=True)
                radar.export_results(db, public / "results.html")
                return
            stamp = radar.now().strftime("%G-W%V")
            edition = config["video"].get("edition", "")
            directory = runtime / "episodes" / stamp / edition if edition else runtime / "episodes" / stamp
            # Re-running a completed week does not upload another version.
            if (directory / "upload.json").exists():
                result = json.loads((directory / "upload.json").read_text())
                if result.get("items"):
                    vid = result["items"][0]["id"]
                    print(f"Diese Woche bereits hochgeladen: https://www.youtube.com/watch?v={vid}")
                    return
            # Reuse rendered files after a failed upload; don't lose fingerprint deduplication.
            if not (directory / "render.json").exists():
                if not (directory / "episode.json").exists():
                    directory = (editor.select(db, config, runtime)
                                 if config.get("automation", {}).get("enabled")
                                 else radar.weekly(db, config, runtime))
                if config.get("ai", {}).get("enabled"):
                    editor.generate(directory, config)
                radar.render(directory, config)
            radar.upload(db, config, runtime, directory, privacy="private")
            editor.previous_features(db, runtime)
        finally:
            db.close()


if __name__ == "__main__":
    main()
