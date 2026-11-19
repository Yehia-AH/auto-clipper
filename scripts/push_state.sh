#!/usr/bin/env bash
# Merge this run's state/processed.json with the copy on GitHub and push it.
# Several runs save at the same time, so retry with a fresh merge if the push races.
git config user.name "auto-clipper"
git config user.email "auto-clipper@users.noreply.github.com"
[ -f state/processed.json ] || exit 0
cp state/processed.json /tmp/mine.json
for attempt in 1 2 3 4 5; do
  git fetch -q origin main
  git reset -q --hard origin/main
  git show origin/main:state/processed.json > /tmp/remote.json 2>/dev/null || echo '{}' > /tmp/remote.json
  cp /tmp/mine.json state/processed.json
  python scripts/save_state.py /tmp/remote.json state/processed.json
  git add state/processed.json
  git diff --cached --quiet && exit 0
  git commit -q -m "Update processed videos"
  git push -q origin HEAD:main && exit 0
  sleep $((attempt * 5))
done
echo "Could not save progress after 5 tries" && exit 1
