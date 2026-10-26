# Logi Dock on Linux

Fixes for the Logitech Logi Dock (USB `046d:0acc`) on Linux with PipeWire/WirePlumber:
clean audio at low volume, volume buttons in sync with the system, a working mic-mute
button with LED, and the Teams button.

Tested on Arch Linux (kernel 7.2), PipeWire with WirePlumber 0.5, niri (Wayland).

## Install

```sh
git clone git@github.com:abdelilah/logi-dock-linux.git
cd logi-dock-linux
./install.sh          # run from a real terminal: it asks for sudo once
```

Requirements: `python3`, `pactl` (from `pipewire-pulse`), `wireplumber` 0.5+, and
`notify-send` (`libnotify`) for the default Teams button action.

After installing, replug the dock once if the buttons don't respond.

### What gets installed

| File | Installed to | Purpose |
|---|---|---|
| `70-logi-dock.rules` | `/etc/udev/rules.d/` | Gives the logged-in user access to the dock's HID interface (buttons, LEDs) |
| `51-logi-dock.conf` | `~/.config/wireplumber/wireplumber.conf.d/` | Uses the dock's hardware volume and ignores its bogus dB range |
| `logi-dockd.py` | `~/.local/bin/logi-dockd` | Daemon for mute LED, call mode and Teams button |
| `logi-dockd.service` | `~/.config/systemd/user/` | Runs the daemon at login |

### Mic-mute and volume keys

The dock's volume keys and mute button reach the desktop as normal
`XF86AudioRaiseVolume` / `XF86AudioLowerVolume` / `XF86AudioMicMute` keys. Your
desktop has to bind them. For niri (`~/.config/niri/config.kdl`, inside `binds`):

```kdl
XF86AudioRaiseVolume { spawn "wpctl" "set-volume" "@DEFAULT_AUDIO_SINK@" "5%+"; }
XF86AudioLowerVolume { spawn "wpctl" "set-volume" "@DEFAULT_AUDIO_SINK@" "5%-"; }
XF86AudioMicMute     { spawn "wpctl" "set-mute"   "@DEFAULT_AUDIO_SOURCE@" "toggle"; }
```

GNOME and KDE handle these keys out of the box.

## How it behaves

- **Volume +/-:** change the system volume, which drives the dock's own hardware
  volume (1-100) one-to-one.
- **Mic mute:** works while an app is using the default mic (a call, a recording).
  The mute LED is red when muted and white when live. When nothing is using the
  mic, the dock leaves call mode and all LEDs go off.
- **Teams button:** runs `--teams-cmd` (default: a desktop notification).
- **Camera button:** sends nothing to the computer; it can't be used.

### Configuration

Edit `~/.config/systemd/user/logi-dockd.service`, then run
`systemctl --user daemon-reload && systemctl --user restart logi-dockd`.

- `--teams-cmd '<shell command>'`: what the Teams button does.
- `--always-in-call`: keep the dock in call mode so mute always works (the
  on-call LED then stays lit).

Logs: `journalctl --user -u logi-dockd -f`

## Uninstall

```sh
systemctl --user disable --now logi-dockd
rm ~/.local/bin/logi-dockd ~/.config/systemd/user/logi-dockd.service
rm ~/.config/wireplumber/wireplumber.conf.d/51-logi-dock.conf
systemctl --user restart wireplumber
sudo rm /etc/udev/rules.d/70-logi-dock.rules
```

## Technical notes

Found by inspecting Logi Tune 3.15.80 for Windows and by testing the dock.

### Audio

- The dock is a standard USB Audio Class 1 device: 48 kHz / 16-bit stereo, speaker
  and echo-cancelling mic.
- Its playback volume control runs from 1 to 100 with a resolution of 1/256 dB.
  That is really a percentage scale mislabelled as dB, so ALSA reports a total
  range of 0.39 dB.
- PipeWire trusts that, so it leaves the hardware level fixed and does nearly all
  attenuation in software on the 16-bit stream. That causes crackling at low
  volume and uneven steps.
- `api.alsa.ignore-dB = true` makes PipeWire map the volume linearly onto the
  hardware control.
- Logi Tune does nothing dock-specific for volume; Windows just uses the endpoint
  volume.

### HID (interface 3)

| Report | Usage page | Contents |
|---|---|---|
| 3 | Telephony headset | In: hook switch, Line, Phone Mute, programmable button. Out byte 1: bit0 Off-Hook (on-call LED), bit1 Mute (mute LED red), then Ring, Hold, Microphone, On-Line, Ringer |
| 2 | Consumer | Vol+, Vol-, Play, Pause, Next, Prev |
| 1 | Vendor `0xFFA0` | Logitech "CPP" protocol (HID++ 2.0-like), 64-byte reports |
| 4 | Vendor `0xFFA1` | Not used by Logi Tune |

- The dock reports **Phone Mute only while the host has set Off-Hook**. Outside a
  call, the mute button sends nothing.
- Pressing **Teams** during a call makes the dock clear its own hook bit (it
  "hangs up"). It also sends a CPP OneTouchJoin event.

### CPP framing (report 1)

```
01 11 LEN | frag | feature-index | (function<<4)|swid | params...   padded to 64 bytes
```

- `frag` is `00` for a single packet. `swid` is `0x0D`.
- Root ping: `01 11 04 00 00 1D nn`.
- Get a feature's index: `01 11 05 00 00 0D <feat_hi> <feat_lo>`. The reply
  contains the index.
- Events have the low nibble of byte 5 set to 0.

Features seen on the dock:

| Feature | Name | Index (this unit) | Notes |
|---|---|---|---|
| `0x010C` | USBHubControl | 7 | |
| `0x010D` | AmbientLED | 10 | fn0 `[action\|0x80, R, G, B, duration u32 ms, period u16 ms]`, action 0=off, 1=solid, 2=pulse, 3=blink; fn1 `[FF]` stops |
| `0x010F` | OneTouchJoin | 12 | Event 0 = Teams button press, `params[0]` = target; fn1 `[on, secs_hi, secs_lo]` lights the Teams LED |

Indices can differ between firmware versions; the daemon looks them up at startup.
