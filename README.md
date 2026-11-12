# Smart Dashboard

A local web dashboard that finds the smart devices on your home network and shows them in one place. It runs on your own PC or Raspberry Pi. Nothing is sent to the cloud.

## Features

- **Automatic discovery:** scans your network at startup and every 5 minutes using ping, port probing, UPnP/SSDP and (optionally) mDNS.
- **Manual scan:** a **Scan network** button runs a new scan whenever you want, with a progress bar.
- **Device types:** sorts devices into cameras, lights, plugs, media, hubs, sensors and other. You can change the type by hand.
- **Add devices by hand:** add any device by IP address, including ones the scan can't see.
- **Cameras:** add a camera with its stream URL and watch it live in the dashboard.
  - `http://` MJPEG or snapshot URLs play directly in the browser.
  - `rtsp://` streams can't play in a browser, so the dashboard shows the URL to open in VLC.
- **Online status:** a green or red dot per device, refreshed every 30 seconds.
- **Persistent:** devices are saved in `devices.json`, so they survive a restart.
- **No required dependencies:** the backend uses only the Python standard library.

## Requirements

- Python 3.8 or newer
- A computer on the same network as your devices (Windows, macOS or Linux)
- Optional: `zeroconf` for better mDNS discovery (Apple, Google and ESPHome devices)

## Quick start

```bash
git clone https://github.com/khalil135711/smart-dashboard.git
cd smart-dashboard
python3 server.py
```

Then open <http://localhost:8765>. From another device on your network, use `http://<ip-of-this-computer>:8765`.

For better mDNS discovery:

```bash
pip install zeroconf
```

## Adding a camera

1. Click **Add device**.
2. Enter a name and the camera's IP address.
3. Set **Type** to *Camera*.
4. Enter the stream URL. Examples (the exact path depends on your camera brand):
   - MJPEG: `http://192.168.1.50/mjpeg`
   - Snapshot (refreshes every 2 seconds if the URL contains `snap` or `jpg`): `http://192.168.1.50/snapshot.jpg`
   - RTSP (opens in VLC, not in the browser): `rtsp://user:password@192.168.1.50:554/stream1`
5. Click **Save device**.

If a scan already found your camera, click **Edit** on its card and add the stream URL there.

## Configuration

Settings are constants at the top of `server.py`:

| Setting | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8765` | Port the dashboard listens on |
| `AUTO_SCAN_SECONDS` | `300` | Time between automatic scans |
| `PROBE_PORTS` | common smart-home ports | Ports checked on each host |
| `OUI` | small list | MAC prefix to brand lookup. Add your own entries. |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/devices` | List devices and scan status |
| `POST` | `/api/scan` | Start a scan |
| `POST` | `/api/devices` | Add a device (`name`, `ip`, `type`, `stream`) |
| `PUT` | `/api/devices/<id>` | Edit a device |
| `DELETE` | `/api/devices/<id>` | Remove a device |

## Limitations

- Scans only the local `/24` subnet (for example `192.168.1.x`). Devices on other VLANs can be added by hand.
- The brand list is short, so many devices appear as "Other". Extend the `OUI` table to improve this.
- The dashboard shows and links to devices. It does not control them (on/off, brightness).
- Some devices don't answer ping and have no open ports, so a scan can miss them. Add them by hand.

## Security

- The dashboard has **no login**. Run it only on a trusted home network and never expose it to the internet.
- `devices.json` can contain camera passwords inside stream URLs. It is listed in `.gitignore` so it isn't committed. Don't share it.
- Only scan networks you own or have permission to scan.

## Troubleshooting

- **No devices found:** check that the computer is on the same network as the devices and that its firewall allows outgoing connections.
- **Dashboard unreachable from your phone:** allow inbound connections on port `8765` in your firewall.
- **Camera image stays black:** open the stream URL directly in a browser tab first to confirm it works. Many cameras need a different path or login.
- **Missing MAC addresses:** the MAC is read from the ARP table, which only works for devices on the same subnet.

## Contributing

Issues and pull requests are welcome. Good first contributions: more brand prefixes, device control for specific brands (Hue, Shelly, Tasmota), and a login option.

## License

Released under the [MIT License](LICENSE).
