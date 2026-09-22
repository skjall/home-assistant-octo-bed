# Octo receiver protocol

How each part was established, so the next person does not start over.

Sources, in order of weight:

1. **Captures from the vendor app** (OCTO Smart Control), posted as Wireshark
   byte dumps in the Home Assistant community thread *"How to setup ESPHome to
   control my bluetooth controlled OctoControl bed"*, and sent unchanged by an
   ESPHome `ble_client` setup that drove two RC2 receivers here for months.
   Marked **[capture]**.
2. **smartbed-mqtt** (`src/Octo/`), an independent implementation used with
   real beds. Marked **[smartbed-mqtt]**.
3. **ha-adjustable-bed** (`beds/octo.py`, `octo_auth.py`), whose author
   describes his notes as derived from the app, without owning a bed. Marked
   **[app notes]** - plausible, not verified against hardware here.

## Transport

| What | Value | Verified against |
| --- | --- | --- |
| Service | `0000ffe0-0000-1000-8000-00805f9b34fb` | capture, both RC2 here |
| Characteristic | `0000ffe1-…`, write and notify | capture |
| Advertised service | `58debc00-4083-4735-8926-6721a778ae5e` | both RC2 here |
| Local name | `RC2` | one RC2 here; the other advertised garbage |

Discovery matches the advertised service first. `ffe0` alone is shared with
other bed families, so it counts only together with a known receiver name.

## Frames

```
40 | cmd_hi cmd_lo | len_hi len_lo | checksum | data … | 40
```

| Offset | Length | Meaning | Verified against |
|-------:|-------:|---------|------------------|
| 0 | 1 | `0x40`, start | capture |
| 1 | 2 | command; a reply sets bit 0 of the first byte | capture, smartbed-mqtt |
| 3 | 2 | data length, big-endian | capture |
| 5 | 1 | checksum | capture |
| 6 | n | data | capture |
| 6+n | 1 | `0x40`, end | capture |

**Checksum:** the two's complement of the byte sum of the whole frame, both
delimiters included and the checksum position counted as zero - so a correct
frame sums to zero. Checked against all nine captured frames **[capture]**.

**Escaping [app notes]:** between the delimiters, `40 → 3C 01`, `3C → 3C 02`,
`4F → 3C 03`, `41 → 3C 04`, applied after the checksum. None of the frames this
integration sends contains one of these bytes, which is why the captures show
no escape. On what the receiver sends, the reader cuts frames by their length
field first - smartbed-mqtt, which works with real receivers, reads replies
that way and knows no escaping - and only falls back to the escaped form when
that does not add up. Cutting at every 0x40 instead lost every record whose
data or checksum happened to contain one; on the RC2 here that cost the motor
count and the PIN record.

## Commands

| Command | Data | Meaning | Verified against |
| --- | --- | --- | --- |
| `02 70` | motor mask | one step up | capture |
| `02 71` | motor mask | one step down | capture |
| `02 73` | - | stop all motors | capture |
| `02 72` | slot (from 0) | one step towards a stored position | smartbed-mqtt, app notes |
| `20 43` | four digits, one raw byte each | PIN | smartbed-mqtt; see below |
| `20 71` | - | list features | smartbed-mqtt |
| `20 72` | feature record | set a feature (light) | capture |

Motor mask: `02` head (M1), `04` feet (M2), `08` M3, `10` M4 **[capture for
02/04/06, smartbed-mqtt for the rest]**.

**Movement is hold-to-run.** A step moves the motor for a fraction of a second;
the app repeats it every 300-350 ms while the button is held and sends a stop
on release **[capture]**. Stored positions work the same way **[app notes]**.

**Light:** `20 72` with the record `00 01 02 | 01 | 01 | 01 | 01 | 00/01` -
feature id `0x000102`, flag, characteristic length and byte, value type, value
**[capture]**.

**PIN:** the capture that circulates with the ESPHome setup,
`40 20 43 00 04 00 02 03 04 05 40`, has a wrong checksum: for the digits 2345
it is `0b`. The digits were changed for the post and the checksum was not.
This package computes it.

## Replies

| Reply | Data | Meaning | Source |
| --- | --- | --- | --- |
| `21 71` | feature record | one entry of the feature listing | smartbed-mqtt |
| `21 43` | `01` or other | PIN accepted, or not | app notes |
| `21 44` | - | the receiver locked itself; send the PIN again | app notes |

Frames may be split across notifications, and one notification may carry
several frames.

### Feature records

```
id (3, big-endian) | flag | char_len | characteristic (char_len) | value type | value …
```

| Id | Meaning | Value |
| --- | --- | --- |
| `000001` | motor count | the RC2 puts it in the characteristic and sends no value: `00 00 01 01 01 02 00` is two motors **[RC2 here]**; `value[0]` where a value is sent **[app notes]** |
| `000002` | stored positions | `value[0]` |
| `000003` | PIN | `value[0] == 1`: a PIN is set; `value[1] == 1`: unlocked |
| `000004` | stored position kinds | one byte per slot |
| `000010` | unknown; the RC2 sends `01 01 01 01 00` | - |
| `000102` | light | present: there is one; `value[0]`: on |
| `FFFFFF` | end of the listing | - |

Source: smartbed-mqtt for the ids and the layout; app notes for `000004`.

Both RC2 receivers here list exactly this, one frame per notification:

```
40 21 71 00 07 e2 00 00 01 01 01 02 00 40      motor count 2
40 21 71 00 08 df 00 01 02 01 01 01 01 00 40   light, off
40 21 71 00 08 d2 00 00 10 01 01 01 01 00 40   000010, unknown
40 21 71 00 06 ea ff ff ff 01 00 00 40         end
```

No PIN record (no PIN set) and no stored positions. The listing is kept with
the config entry and read again at every start, so a correction here reaches
existing entries without a new connection.
There are no position or status reports.

## Timing

A receiver with a PIN set drops the link after about 30 seconds without the
PIN **[app notes, forum]**, hence the keepalive.

## Deliberately absent

- **Storing a position** (`10 70`). It overwrites what the user stored with the
  remote, from an automation that may misfire. The remote does it better.
- **Synchronised drive mode** (`10 71`). It changes how the receiver pairs with
  its twin in a split bed frame, a setting nobody changes twice.
- **RGB light** (`000104`). Not verified against any receiver here.
