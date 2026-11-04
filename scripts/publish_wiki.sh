#!/usr/bin/env bash
# Publish the pages in wiki/ to the GitHub wiki of this repository.
#
# GitHub keeps a wiki in a separate git repository (<repo>.wiki.git). It exists only after the wiki has been
# created once: open https://github.com/saiteja195/MemoryAtlas/wiki and press "Create the first page" (save any
# text; this script overwrites it). Then run, from a clone where you can push to the wiki:
#
#   scripts/publish_wiki.sh                 # publish to origin's wiki
#   scripts/publish_wiki.sh <wiki-git-url>  # or to another wiki repository (for example a local one, to try it)
#
# Every page file in wiki/ is copied over; pages in the wiki that are not in wiki/ are removed, so wiki/ stays the
# single source. The commit is authored as saiteja195 (see CONTRIBUTING.md).
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
src="$root/wiki"
url="${1:-$(git -C "$root" remote get-url origin | sed -E 's#(\.git)?$#.wiki.git#')}"

[ -d "$src" ] || { echo "no wiki/ folder in $root" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --quiet "$url" "$tmp/wiki" || {
  echo "Could not clone $url. Has the wiki been created? Open the repository's Wiki tab and create the first page." >&2
  exit 1
}
cd "$tmp/wiki"
find . -mindepth 1 -maxdepth 1 -not -name .git -exec rm -rf {} +
cp "$src"/*.md .
git config user.name "saiteja195"
git config user.email "108951028+saiteja195@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "The wiki is already up to date."
  exit 0
fi
git commit --quiet -m "docs(wiki): publish pages from wiki/"
git push --quiet origin HEAD
echo "Published $(ls "$src"/*.md | wc -l | tr -d ' ') pages to $url"
