#!/usr/bin/env bash
# Publish each clipped video folder listed in .last_run.json (or the list file given
# as $1) as a GitHub release. $2 = optional extra tag part (e.g. "h3" for a live hour).
LIST="${1:-.last_run.json}"
i=0
[ -f "$LIST" ] || exit 0
for dir in $(python -c "import json,sys;print(' '.join(json.load(open(sys.argv[1]))))" "$LIST"); do
  i=$((i+1))
  ls "$dir"/*.mp4 >/dev/null 2>&1 || continue
  title=$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['title'][:100])" "$dir/manifest.json")
  {
    echo "$title"
    echo
    for t in "$dir"/*.txt; do echo "### $(basename "${t%.txt}")"; echo; cat "$t"; echo; done
  } > notes.md
  gh release create "clips-${GITHUB_RUN_ID}-${2:+$2-}${i}" "$dir"/*.mp4 "$dir"/*.txt \
    --title "📦 $title" --notes-file notes.md
done
