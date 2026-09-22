# Octo Bed (BLE)

Home Assistant integration for adjustable beds driven by an Octo receiver (the
RC2 and its relatives) over Bluetooth Low Energy - the ones the vendor's
*OCTO Smart Control* app talks to.

It raises and lowers the motors, drives the bed flat or to a stored position,
and switches the under-bed light. Everything happens locally, typically
through an ESPHome Bluetooth proxy next to the bed. No cloud, no vendor
account, and no microcontroller of its own per bed.

It connects only while there is something to say. A command opens a
connection, and a few seconds after the last one it is closed again, so the
bed never occupies one of the proxy's few connection slots for longer than it
is in use.

## Supported devices

Octo receivers that advertise the Octo service `58debc00-4083-4735-8926-6721a778ae5e`,
or service `ffe0` under one of the receiver names the vendor app knows (`RC2`,
`RC3`, `MC1`, `MC2`, `RTV`, `L2M`, `CLI`, `BMB`, `BMS`, `BM3`, `OctoBrick`,
`OctoIQ`). Verified against:

| Receiver | Motors | Light | PIN |
| --- | --- | --- | --- |
| RC2 | 2 (head, feet) | yes | yes |

A bed frame with two separately driven sides has two receivers. Each one is a
device and a config entry of its own.

The *Star2* variant of Octo uses a different protocol and is not supported.

## What you get

Which entities appear is decided by the bed itself: during setup the receiver
is asked for its motors, stored positions and light, and only those are
created.

| Entity | Kind | Notes |
| --- | --- | --- |
| Head, Feet, Motor 3, Motor 4 | cover | one per motor the receiver reports; open raises, close lowers |
| All motors | cover | only with more than one motor; drives them together |
| Stop | button | stops every motor |
| Flat | button | lowers every motor until the bed is flat |
| Memory position *n* | button | one per stored position the receiver reports |
| Light | light | only if the receiver has one |
| Connection | binary sensor | diagnostic, disabled by default; on while a connection is open |

The receiver reports neither motor positions nor the light's state. The covers
therefore show *opening* or *closing* while a movement runs and *unknown*
otherwise, and the light shows what Home Assistant last switched.

## Use cases

- **Reading position at the press of a button.** An automation or a wall
  switch raises the head end for a fixed number of steps.
- **Flat at night.** When everyone is in bed and the lights go out, the bed
  goes flat.
- **A night light that finds the floor.** The under-bed light switches on with
  a motion sensor and off again after a minute.
- **A stored position as part of a scene.** *Memory position 1* in a
  "reading" scene next to the bedside lamps.

## Examples

Raise the head end for the configured number of steps:

```yaml
action: cover.open_cover
target:
  entity_id: cover.jan_head
```

Flat when the bedroom light goes out after 22:00:

```yaml
automation:
  - alias: "Bed flat at night"
    triggers:
      - trigger: state
        entity_id: light.bedroom_ceiling
        to: "off"
    conditions:
      - condition: time
        after: "22:00:00"
    actions:
      - action: button.press
        target:
          entity_id:
            - button.jan_flat
            - button.wiebke_flat
```

Under-bed light with a motion sensor:

```yaml
automation:
  - alias: "Under-bed light at night"
    triggers:
      - trigger: state
        entity_id: binary_sensor.bedroom_motion
        to: "on"
    actions:
      - action: light.turn_on
        target:
          entity_id: light.jan_light
      - delay: "00:01:00"
      - action: light.turn_off
        target:
          entity_id: light.jan_light
```

## How data is fetched

There is nothing to fetch: the receiver reports no state. Home Assistant only
listens to its advertisements, which is what decides whether the bed counts as
in range.

A command connects. The receiver moves a motor only while the command keeps
arriving, so a movement is a series of *steps* at a fixed interval, followed by
a stop. The first step is sent before the action returns, so a bed that cannot
be reached fails the action you took. The rest runs in the background.

After the last command - or when a movement has finished - the connection
stays open for the idle timeout, so that a quick second command does not have
to connect again, and is then closed. While it is open and the bed has a PIN,
the PIN is repeated every few seconds, because a locked receiver hangs up
after about 30 seconds without it.

Before connecting, the integration checks whether any adapter that hears the
bed still has a free connection slot, and says so if none has.

## Requirements

- Home Assistant 2026.5 or newer.
- A connectable Bluetooth adapter or an ESPHome Bluetooth proxy within range of
  the bed. An ESP32 proxy offers three connection slots by default, shared
  with every other device that connects through it.
- The bed must not be held by anything else. The receiver accepts one
  connection at a time: while the vendor app, or an ESPHome device with a
  `ble_client` for it, is connected, Home Assistant cannot.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=skjall&repository=home-assistant-octo-bed&category=integration)

Install *Octo Bed (BLE)* there, then restart Home Assistant.

Should the button not work, add the repository by hand: HACS → three-dot menu
→ *Custom repositories* → this repository's URL, category *Integration*.

### Manually

Copy `custom_components/octo_bed` into your Home Assistant `config` directory
so that it ends up at `config/custom_components/octo_bed`, then restart.

## Setup

Beds in range are discovered on their own - *Settings → Devices & Services*
will offer them. Otherwise start the setup here:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=octo_bed)

Setup connects once and asks the receiver what it has. If a PIN is set on the
bed, you are asked for it, and it is tried on the bed before the entry is
created.

The entry is named after the receiver and the end of its address, for example
`RC2 4B63`. Two receivers of one bed frame advertise the same name, so rename
each entry after the side it drives.

## Configuration

Under the integration's *Configure*:

- **Step interval** (default 300 ms) - the time between two steps of a
  movement. The vendor app sends one every 300 to 350 ms; much longer and the
  motor stutters.
- **Steps per movement** (default 50) - how many steps one open or close runs.
  Steps times interval is the longest a single movement lasts: 15 seconds by
  default. *Stop* ends it early.
- **Steps to flat or a stored position** (default 100) - the same for *Flat*
  and the memory buttons, which need long enough to arrive. The receiver stops
  on its own once the position is reached.
- **Hang up after** (default 10 s) - how long the connection stays open after
  the last command. Shorter frees the proxy's slot sooner; longer saves a
  reconnect when several commands follow each other.
- **PIN repeat interval** (default 25 s) - only used when the bed has a PIN.

*Reconfigure* asks the bed again which motors, stored positions and light it
has, and changes the PIN.

## Removal

*Settings → Devices & Services → Octo Bed (BLE) → Delete*. If installed
through HACS, uninstall it there as well and restart.

## Notes and limitations

- **One connection at a time.** While Home Assistant is connected, the vendor
  app cannot connect, and vice versa. With the default idle timeout that is
  never longer than a movement plus ten seconds.
- **No positions.** The receiver does not report where the motors are, so the
  covers cannot be set to a percentage.
- **The light's state is assumed.** It is what Home Assistant last switched;
  the receiver switches it off by itself after a while and does not say so.
- **Stop stops everything.** The receiver has one stop command for all motors.
- Storing a position, the RGB light of some receivers and the synchronised
  drive mode are known from the protocol but not exposed; see
  [docs/protocol.md](docs/protocol.md).

## Troubleshooting

**Entities are unavailable.** No adapter hears the bed. *Settings → Devices &
Services → Bluetooth* lists what each adapter hears; the bed appears under its
receiver name, typically `RC2`. A receiver that is connected to something else
stops advertising - check for the vendor app or an old ESPHome `ble_client`.

**"No free connection slot".** Every adapter that hears the bed has all its
slots taken. Enable the *Connection* sensor of each bed to see whether one of
them stays connected, lower *Hang up after*, or give the proxy more slots
(`bluetooth_proxy: connection_slots:` in ESPHome, at the cost of memory).

**The action fails with "did not take the command".** The connection broke
off. Usually range: a proxy in the same room, not behind the bed frame, helps
more than anything else.

**The bed moves in short jerks.** The step interval is too long for this
receiver. Lower it towards 300 ms.

**The bed stops before it gets there.** Raise *Steps per movement* or *Steps
to flat or a stored position*.

**Everything worked, now the PIN is refused.** The PIN was changed in the app.
Home Assistant asks for the new one.

For a bug report, attach the diagnostics from the integration's three-dot menu.
They contain the features the receiver reported, the timings, and the
connection paths with their free slots - without the PIN or the bed's address.

## How this works

The protocol - frames, checksum, commands, the feature listing and the PIN
exchange - is documented in [docs/protocol.md](docs/protocol.md), together
with where each part was established. The wire format lives in its own package,
[`octo-bed-protocol`](lib/octo_bed_protocol), which opens no connections and
can be read and tested without hardware.

This is interoperability work: it lets an independently written program talk
to hardware you own. No vendor code is copied into this repository.

Not affiliated with, endorsed by, or supported by Octo. All trademarks belong
to their owners.

## License

MIT - see [LICENSE](LICENSE).
