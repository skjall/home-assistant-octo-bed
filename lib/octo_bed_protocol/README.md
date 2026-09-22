# octo-bed-protocol

The wire protocol of Octo adjustable bed controllers (the RC2 receiver and its
relatives) over Bluetooth Low Energy, as used by the
[Octo Bed](https://github.com/skjall/home-assistant-octo-bed) Home Assistant
integration.

It builds frames and reads replies. It opens no connections and depends on no
Bluetooth stack, so it can be used and tested without hardware.

```python
import octo_bed_protocol as octo

octo.move(octo.MOTOR_HEAD, up=True).hex(" ")  # '40 02 70 00 01 0b 02 40'
octo.stop().hex(" ")  # '40 02 73 00 00 0b 40'

reader = octo.FrameReader()
features = octo.Features()
for packet in reader.feed(notification):
    features.add(packet)
```

Every frame goes to characteristic `ffe1` of service `ffe0`. How each byte was
established is recorded in
[docs/protocol.md](https://github.com/skjall/home-assistant-octo-bed/blob/main/docs/protocol.md).

Not affiliated with, endorsed by, or supported by Octo. All trademarks belong
to their owners.
