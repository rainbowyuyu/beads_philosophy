"""Explicitly refresh the Modrinth metadata lock; never downloads or runs JARs.

Run only when intentionally reviewing a new version set. Do not overwrite an
existing lock without reviewing the diff and JAR-level dependencies afterwards.
"""
from pathlib import Path
import argparse
import datetime
import json
import urllib.parse
import urllib.request


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "beads-philosophy/0.1 (official mod resource index)"})
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.load(response)


def build_lock(game_version="1.21.1"):
    query = urllib.parse.urlencode({"game_versions": json.dumps([game_version]), "loaders": json.dumps(["fabric"])})
    mods = []
    for slug in ["litematica", "malilib", "replaymod", "fabric-api"]:
        project_url = f"https://api.modrinth.com/v2/project/{slug}"
        project = get_json(project_url)
        versions_url = project_url + "/version?" + query
        versions = get_json(versions_url)
        stable = [v for v in versions if v["version_type"] == "release"]
        if not stable:
            raise ValueError(f"No stable Fabric {game_version} release for {slug}")
        version = stable[0]
        files = [f for f in version["files"] if f["filename"].endswith(".jar")]
        file = next((f for f in files if f.get("primary")), files[0])
        mods.append({
            "slug": slug, "title": project["title"], "project_id": project["id"],
            "project_url": "https://modrinth.com/mod/" + slug,
            "source_url": project["source_url"], "license": project["license"]["id"],
            "version_id": version["id"], "version": version["version_number"],
            "game_versions": version["game_versions"], "loaders": version["loaders"],
            "dependencies": version["dependencies"],
            "file": {k: file[k] for k in ["filename", "url", "hashes", "size"]},
            "evidence_url": "https://api.modrinth.com/v2/version/" + version["id"],
        })
    return {
        "schema_version": 1,
        "checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "minecraft_edition": "Java", "minecraft_version": game_version, "loader": "Fabric",
        "validation": "Official metadata matches the same game version/loader; this is not an in-game compatibility test.",
        "mods": mods,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-version", default="1.21.1")
    parser.add_argument("--out", type=Path, required=True, help="New lock filename; refuses to overwrite")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; choose a new candidate filename")
    lock = build_lock(args.game_version)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(lock, output, ensure_ascii=False, indent=2)
        output.write("\n")
