# CLAUDE.md

Guidance for Claude Code in this repository.

The development ground rules are shared across integrations and are kept up to date by ha-integration-standards:

@docs/ha-integration-standards.md

## About this integration

The device is the Octo receiver of an adjustable bed (RC2 and relatives). It
replaces an ESPHome device that held a standing `ble_client` connection to
each bed. The central decision of this repository follows from that:

**No standing connections.** An ESPHome Bluetooth proxy has three connection
slots by default, shared with every device it serves. A command connects; the
connection is closed after `idle_timeout` without one. Nothing may hold a
connection open by itself - no polling, no reconnect loop, no keepalive
outside an open session. The *Connection* binary sensor exists to make a
violation visible.

The receiver reports nothing about its state, so there is nothing to poll: the
coordinator only listens to advertisements for availability. Movements are
hold-to-run - a series of steps at `step_interval`, then a stop - and run in a
background task after the first step has been sent.

Which entities exist is decided by the receiver's feature listing, read during
setup and reconfigure and stored in the entry. Nothing is hard-coded per bed.

The wire format lives in `lib/octo_bed_protocol/`, published to PyPI and pinned
with `==` in the manifest. [docs/protocol.md](docs/protocol.md) records where
each command and offset comes from - change one, change the other, and say
what you verified it against.

The PIN is the only secret. It is redacted from diagnostics.
