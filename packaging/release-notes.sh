#!/bin/sh
# Print the CHANGELOG.md section for one version: the lines after
# "## <version>" up to the next "## " heading. Exits 1 when there is no such
# section, or it's empty, so a release can't go out with blank notes.
#   packaging/release-notes.sh 5.6.0 [CHANGELOG.md]
set -eu
version="$1"
changelog="${2:-CHANGELOG.md}"
notes=$(awk -v v="$version" '
    /^## / { if (found) exit; found = ($2 == v); next }
    found
' "$changelog")
if [ -z "$(printf '%s' "$notes" | tr -d '[:space:]')" ]; then
    echo "No notes for $version in $changelog" >&2
    exit 1
fi
printf '%s\n' "$notes"
