#!/bin/bash
# NOT a launcher: replace after root trust review with a fixed argv dispatch.
# Mount only isolated clone game/prefix directories as writable.
# Never source a user-owned env hook from a privileged process.
printf '%s\n' 'No game configured; supply your own reviewed foreground launcher.' >&2
exit 125
