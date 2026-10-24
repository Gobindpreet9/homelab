#!/bin/bash
set -e
source /opt/gow/bash-lib/utils.sh
source /opt/gow/launch-comp.sh
export RUN_SWAY=1
unset RUN_GAMESCOPE
export SWAY_STOP_ON_APP_EXIT=yes
# The client waits for host-side exclusion and successful pre-session save sync.
launcher /opt/wolf/launch-client.sh
