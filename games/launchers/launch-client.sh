#!/bin/bash
# Run the game client. Only stop the nested compositor ourselves when the launch
# failed (e.g. refused by the save-safety gate). On a normal exit the GoW launcher's
# own `&& killall sway` stops it; doing both made sway segfault on shutdown.
set +e
# Keep the DualSense (gyro/touchpad still reach the game through its own
# evdev nodes), but stop sway/libinput from turning the touchpad into a mouse
# pointer, which made games flip between pad and mouse UI (flashing prompts,
# "frozen" controller). Applies to current and future touchpads.
swaymsg -s "$SWAYSOCK" 'input type:touchpad events disabled' >/dev/null 2>&1 || true
swaymsg -s "$SWAYSOCK" 'seat * hide_cursor 1000' >/dev/null 2>&1 || true
# Some Proton games map untitled helper windows; these optional static rules
# keep them off screen without a polling watcher. Review for each title.
for c in 'no_focus [title="^$" app_id="^(steam_proton|steam_app_[0-9]+)$"]' \
         'no_focus [title="^$" class="^(steam_proton|steam_app_[0-9]+)$"]' \
         'for_window [title="^$" app_id="^(steam_proton|steam_app_[0-9]+)$"] move scratchpad' \
         'for_window [title="^$" class="^(steam_proton|steam_app_[0-9]+)$"] move scratchpad' \
         'for_window [title="."] fullscreen enable'; do
    swaymsg -s "$SWAYSOCK" "$c" >/dev/null 2>&1 || true
done
# TV session: no status bar.
pkill -x waybar >/dev/null 2>&1 || true
swaymsg -s "$SWAYSOCK" 'bar * mode invisible' >/dev/null 2>&1 || true
/usr/bin/python3 -I /opt/wolf/app_client.py
status=$?
if [ "$status" -ne 0 ]; then
    swaymsg -s "$SWAYSOCK" exit >/dev/null 2>&1 || true
fi
exit "$status"
