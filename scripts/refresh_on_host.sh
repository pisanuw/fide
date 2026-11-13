#!/bin/bash
# Monthly FIDE list refresh, run by launchd on halflife (see scripts/install_launchd.sh).
#
# Runs in a dedicated clone that stays on main. Pulls main, downloads and validates
# the current FIDE list (scripts/fetch_fide.py), runs the tests, and commits and
# pushes players/YYYYMM to main only when a new month arrived. Render redeploys
# from that push.
#
#   scripts/refresh_on_host.sh           normal run
#   scripts/refresh_on_host.sh --check   verify python, git fetch/push access and FIDE reachability; change nothing
#
# Environment: PYTHON (default: python3, must be 3.10+), FIDE_BRANCH (default: main).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${FIDE_BRANCH:-main}"
PYTHON="${PYTHON:-python3}"
LOCK="$REPO/.refresh.lock"
MODE="${1:-run}"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*"; exit 1; }

cd "$REPO"
mkdir "$LOCK" 2>/dev/null || die "another refresh is running ($LOCK exists; remove it if stale)"
trap 'rmdir "$LOCK"' EXIT

log "refresh start in $REPO ($MODE)"

# -- preconditions: dedicated clone on $BRANCH with no local edits -----------
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || die "clone is not on $BRANCH; this script needs a dedicated clone"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "clone has uncommitted changes; this script needs a dedicated clone"

"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || die "$PYTHON is older than 3.10; set PYTHON to a newer interpreter"

# -- python venv, reinstalled only when requirements change ------------------
VENV="$REPO/.venv"
[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
VPY="$VENV/bin/python"
want="$("$VPY" -c 'import hashlib; print(hashlib.sha256(open("requirements-dev.txt","rb").read()).hexdigest())')"
if [ "$(cat "$VENV/.req-hash" 2>/dev/null || true)" != "$want" ]; then
  log "installing requirements"
  "$VPY" -m pip install -q --upgrade pip
  "$VPY" -m pip install -q -r requirements-dev.txt
  echo "$want" > "$VENV/.req-hash"
fi

# -- sync with GitHub ---------------------------------------------------------
git fetch -q origin "$BRANCH"
git merge -q --ff-only "origin/$BRANCH" || die "local $BRANCH has diverged from origin/$BRANCH"

if [ "$MODE" = "--check" ]; then
  git push --dry-run -q origin "$BRANCH" || die "cannot push to origin/$BRANCH (credentials?)"
  "$VPY" -c 'import urllib.request as u; r = u.urlopen(u.Request("https://ratings.fide.com/download/players_list.zip", method="HEAD"), timeout=60); print("FIDE reachable:", r.status, r.headers.get("Last-Modified"))'
  "$VPY" -m pytest -q
  log "check ok"
  exit 0
fi

# -- download, validate, test, publish ---------------------------------------
out="$("$VPY" scripts/fetch_fide.py)"
printf '%s\n' "$out"
changed="$(printf '%s\n' "$out" | sed -n 's/^changed=//p' | tail -1)"
month="$(printf '%s\n' "$out" | sed -n 's/^month=//p' | tail -1)"
if [ "$changed" != "true" ]; then
  log "no new month; done"
  exit 0
fi

"$VPY" -m pytest -q
"$VPY" -c "from app.index import PlayerIndex, find_data_file; ix = PlayerIndex.from_zip(find_data_file('players')); r = ix.search('carlsen'); assert r, 'no results'; print(len(ix), 'players; top hit', r[0]['name'])"

git add "players/$month"
if git diff --cached --quiet; then
  log "players/$month is identical to what is committed; nothing to push"
  exit 0
fi
git commit -q -m "Add FIDE players list $month"
for attempt in 1 2 3; do
  if git push -q origin "HEAD:$BRANCH"; then
    log "pushed players/$month to $BRANCH"
    exit 0
  fi
  log "push failed (attempt $attempt); rebasing on origin/$BRANCH and retrying"
  sleep $((attempt * 30))
  git pull -q --rebase origin "$BRANCH"
done
die "push failed after 3 attempts; the commit is local in $REPO"
