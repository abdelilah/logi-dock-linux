#!/bin/sh
# Install the Logi Dock fixes for the current user.
#   - udev rule (needs sudo): gives your session access to the dock's HID nodes
#   - WirePlumber rule: use the dock's hardware volume, ignore its bogus dB range
#   - logi-dockd user service: mute LED, in-call mode, Teams button
set -e
cd "$(dirname "$0")"

if ! cmp -s 70-logi-dock.rules /etc/udev/rules.d/70-logi-dock.rules; then
    sudo install -Dm644 70-logi-dock.rules /etc/udev/rules.d/70-logi-dock.rules
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=input
fi

install -Dm644 51-logi-dock.conf ~/.config/wireplumber/wireplumber.conf.d/51-logi-dock.conf
systemctl --user restart wireplumber

install -Dm755 logi-dockd.py ~/.local/bin/logi-dockd
install -Dm644 logi-dockd.service ~/.config/systemd/user/logi-dockd.service
systemctl --user daemon-reload
systemctl --user enable --now logi-dockd.service
systemctl --user --no-pager status logi-dockd.service | head -5
