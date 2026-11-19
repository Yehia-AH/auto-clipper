#!/usr/bin/env bash
# Publish each clipped video folder listed in .last_run.json as a GitHub release.
i=0
[ -f .last_run.json ] || exit 0
for dir in $(python -c "import json;print(' '.join(json.load(open('.last_run.json'))))"); do
  i=$((i+1))
  ls "$dir"/*.mp4 >/dev/null 2>&1 || continue
  title=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['title'][:100])" "$dir/manifest.json")
  {
    echo "$title"
    echo
    for t in "$dir"/*.txt; do echo "### $(basename "${t%.txt}")"; echo; cat "$t"; echo; done
  } > notes.md
  gh release create "clips-${GITHUB_RUN_ID}-${i}" "$dir"/*.mp4 "$dir"/*.txt \
    --title "📦 $title" --notes-file notes.md
done
