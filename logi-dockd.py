#!/usr/bin/env python3
"""logi-dockd: Logi Dock (046d:0acc) button/LED helper for Linux.

What the dock does (found by inspecting Logi Tune 3.15 and the device itself):
  * HID report 3 (Telephony): the dock only reports mic-mute presses while the
    host has set its Off-Hook output bit ("in call"). Output byte bits:
    bit0 Off-Hook (on-call LED), bit1 Mute (mute LED red instead of white).
    Phone Mute presses reach the desktop as KEY_MICMUTE via the kernel.
  * HID report 1 (vendor "CPP" protocol, HID++ 2.0-like):
      01 11 LEN | frag | feature-index | fn<<4|swid | params...
    Feature 0x010F (OneTouchJoin) emits event 0 when the Teams button is pressed.
  * Volume +/- are plain consumer keys; the camera button emits nothing.

This daemon:
  * puts the dock "in call" while any app records from the default mic, so
    the mute button works then, and drops it back out when the mic is idle;
  * mirrors the default mic's mute state on the mute LED;
  * runs --teams-cmd when the Teams button is pressed.
"""
import argparse
import glob
import os
import select
import subprocess
import sys
import time

SWID = 0x0D
FEAT_ONE_TOUCH_JOIN = 0x010F
OFF_HOOK, MUTE = 0x01, 0x02


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def find_hidraw():
    for ue in glob.glob('/sys/class/hidraw/hidraw*/device/uevent'):
        with open(ue) as f:
            if 'HID_ID=0003:0000046D:00000ACC' in f.read():
                return '/dev/' + ue.split('/')[4]
    return None


class Dock:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)
        self.otj = self.feature_index(FEAT_ONE_TOUCH_JOIN)
        self.leds = None

    def close(self):
        os.close(self.fd)

    def cpp_send(self, idx, fn, params=b''):
        msg = bytes([0, idx, (fn << 4) | SWID]) + bytes(params)
        pkt = bytes([1, 0x11, len(msg)]) + msg
        os.write(self.fd, pkt + bytes(64 - len(pkt)))

    def feature_index(self, feat):
        self.cpp_send(0, 0, [feat >> 8, feat & 0xFF])
        end = time.time() + 1
        while time.time() < end:
            if select.select([self.fd], [], [], 0.2)[0]:
                d = os.read(self.fd, 64)
                if d[0] == 1 and d[4] == 0 and d[5] == SWID:
                    return d[6] or None
        return None

    def set_leds(self, bits, force=False):
        if bits != self.leds or force:
            os.write(self.fd, bytes([3, bits, 0]))
            self.leds = bits

    def read(self):
        """Return 'teams' for a Teams button press, 'hook' if the dock changed
        its own hook state (it hangs up itself when Teams is pressed in a call)."""
        d = os.read(self.fd, 64)
        if d[0] == 1 and self.otj and d[4] == self.otj and d[5] == 0x00:
            return 'teams'
        if d[0] == 3 and self.leds is not None and (d[1] & 1) != (self.leds & OFF_HOOK):
            return 'hook'
        return None


def pactl(*args):
    return subprocess.run(['pactl', *args], capture_output=True, text=True).stdout


def audio_state():
    """(mic_in_use, mic_muted) for the default source."""
    src = pactl('get-default-source').strip()
    muted = 'yes' in pactl('get-source-mute', src)
    # map source index -> name, then look for recording streams on it
    idx = None
    for line in pactl('list', 'short', 'sources').splitlines():
        cols = line.split('\t')
        if len(cols) > 1 and cols[1] == src:
            idx = cols[0]
    in_use = False
    for line in pactl('list', 'short', 'source-outputs').splitlines():
        cols = line.split('\t')
        if len(cols) > 1 and cols[1] == idx:
            in_use = True
    return in_use, muted


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--teams-cmd', default='',
                    help='shell command to run when the Teams button is pressed')
    ap.add_argument('--always-in-call', action='store_true',
                    help='keep the dock in call mode so mute always works '
                         '(on-call LED stays lit)')
    args = ap.parse_args()

    sub = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, text=True, bufsize=1)
    dock = None
    while True:
        if dock is None:
            path = find_hidraw()
            if path:
                try:
                    dock = Dock(path)
                    log('dock connected on', path, 'OneTouchJoin index', dock.otj)
                except OSError as e:
                    log('cannot open', path, e)
            if dock is None:
                # drain audio events while waiting for the dock
                if select.select([sub.stdout], [], [], 2)[0]:
                    sub.stdout.readline()
                continue

        in_use, muted = audio_state()
        bits = 0
        if in_use or args.always_in_call:
            bits = OFF_HOOK | (MUTE if muted else 0)
        try:
            dock.set_leds(bits)
            r = select.select([dock.fd, sub.stdout], [], [], 5)[0]
            if dock.fd in r:
                ev = dock.read()
                if ev == 'teams':
                    log('teams button')
                    if args.teams_cmd:
                        subprocess.Popen(args.teams_cmd, shell=True)
                if ev:  # the dock drops its hook state on Teams press; restore ours
                    dock.set_leds(bits, force=True)
            if sub.stdout in r:
                sub.stdout.readline()
        except OSError:
            log('dock disconnected')
            dock.close()
            dock = None


if __name__ == '__main__':
    main()
