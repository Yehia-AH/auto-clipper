"""Merge this run's state/processed.json with the latest one on GitHub.

Several runs can finish around the same time (the hourly check plus videos you
started by hand), so a plain push could fail or drop another run's progress.
Usage: python scripts/save_state.py <remote_state.json> <local_state.json>
Writes the merged result over the local file.
"""
import json
import sys


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


remote, local = load(sys.argv[1]), load(sys.argv[2])
merged = {
    "processed": {**remote.get("processed", {}), **local.get("processed", {})},
    "failures": {**remote.get("failures", {}), **local.get("failures", {})},
    "partial": {},
}
for vid in set(remote.get("partial", {})) | set(local.get("partial", {})):
    if vid in merged["processed"]:
        continue  # finished by one of the runs
    merged["partial"][vid] = max(remote.get("partial", {}).get(vid, 0),
                                 local.get("partial", {}).get(vid, 0))
merged["partial_urls"] = {vid: u for vid, u in
                          {**remote.get("partial_urls", {}), **local.get("partial_urls", {})}.items()
                          if vid in merged["partial"]}
for vid in list(merged["failures"]):
    if vid in merged["processed"]:
        merged["failures"].pop(vid)

with open(sys.argv[2], "w") as f:
    json.dump(merged, f, indent=2, sort_keys=True)
    f.write("\n")
