#!/bin/bash
# Local (PC) launcher for streamed games. Takes the same per-game lock as TV
# sessions: refuses while the TV is playing, syncs saves before and after play.
# Usage: local-launch.sh example-game|second-game
set -uo pipefail
game="${1:?game id}"
case "$game" in
  example-game) title="Example Game" ;;
  second-game)  title="Second Game" ;;
  *) echo "unknown game: $game" >&2; exit 64 ;;
esac
log="/srv/homelab/games/logs/local-$game.log"
mkdir -p "$(dirname "$log")"
/usr/bin/python3 -I /usr/local/lib/wolf-streaming/host_guard.py local "$game" 2> >(tee -a "$log" >&2)
code=$?
if [ "$code" -ne 0 ] && grep -q 'BLOCKED' <(tail -n 3 "$log"); then
    reason="$(grep 'BLOCKED' "$log" | tail -n 1)"
    case "$reason" in
      *"already active"*) body="$title is being played on the TV right now. Quit it on the TV first, then launch here — your progress will be synced." ;;
      *"save sync failed with status 2"*) body="Save conflict for $title. Both versions were kept; ask for help before launching." ;;
      *) body="$title was not started to protect your saves: ${reason#BLOCKED: }" ;;
    esac
    notify-send -u critical -a "Game streaming" "$title not launched" "$body" 2>/dev/null || true
fi
exit "$code"
