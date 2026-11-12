#!/usr/bin/env python3
"""Local smart-home dashboard backend. Python 3.8+, no required dependencies.
Optional: `pip install zeroconf` for better mDNS (Bonjour/Chromecast/HomeKit) discovery.
Run:  python3 server.py   ->  open http://localhost:8765  (or http://<this-pc-ip>:8765)
"""
import concurrent.futures as cf, ipaddress, json, os, platform, re, socket, subprocess, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "devices.json")
PORT = 8765
AUTO_SCAN_SECONDS = 300
PROBE_PORTS = [80, 443, 554, 8554, 8080, 8000, 1883, 8123, 8008, 8009, 1400, 55443, 6668, 5683, 7000, 9100]

# Small vendor hints from MAC prefixes (extend as you like)
OUI = {
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    "24:0a:c4": "Espressif", "30:ae:a4": "Espressif", "a4:cf:12": "Espressif", "84:0d:8e": "Espressif", "bc:dd:c2": "Espressif",
    "44:19:b6": "Hikvision", "c0:56:e3": "Hikvision", "bc:ad:28": "Hikvision",
    "3c:ef:8c": "Dahua", "90:02:a9": "Dahua", "e0:50:8b": "Dahua",
    "00:17:88": "Philips Hue", "00:0e:58": "Sonos", "b8:e9:37": "Sonos",
    "f4:f5:d8": "Google", "3c:5a:b4": "Google", "fc:65:de": "Amazon", "44:65:0d": "Amazon",
    "50:c7:bf": "TP-Link", "98:da:c4": "TP-Link",
}
lock = threading.Lock()
devices = {}
scan = {"running": False, "progress": 0, "found": 0, "last": None, "error": None}


def load():
    global devices
    try:
        with open(DB) as f:
            devices = json.load(f)
    except Exception:
        devices = {}


def save():
    with lock, open(DB, "w") as f:
        json.dump(devices, f, indent=2)


def local_subnet():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the LAN interface
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip, ipaddress.ip_network(ip + "/24", strict=False)


def ping(ip):
    win = platform.system() == "Windows"
    cmd = ["ping", "-n", "1", "-w", "700", ip] if win else ["ping", "-c", "1", "-W", "1", ip]
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except Exception:
        return False


def open_ports(ip, ports=PROBE_PORTS, timeout=0.5):
    found = []
    for p in ports:
        try:
            with socket.create_connection((ip, p), timeout=timeout):
                found.append(p)
        except OSError:
            pass
    return found


def arp_table():
    try:
        out = subprocess.run(["arp", "-an"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return {}
    table = {}
    for ip, mac in re.findall(r"(\d+\.\d+\.\d+\.\d+)\)?\s+(?:at\s+)?([0-9a-fA-F]{1,2}(?:[:-][0-9a-fA-F]{1,2}){5})", out):
        mac = ":".join(x.zfill(2) for x in re.split(r"[:-]", mac.lower()))
        if mac not in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
            table[ip] = mac
    return table


def ssdp(seconds=3):
    """UPnP discovery: returns {ip: {server, location}}"""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n").encode()
    res = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.5)
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + seconds
        while time.time() < end:
            try:
                data, (ip, _) = s.recvfrom(4096)
            except socket.timeout:
                continue
            h = dict(re.findall(r"^([A-Za-z-]+):\s*(.*)$", data.decode(errors="ignore"), re.M))
            res.setdefault(ip, {"server": h.get("SERVER", ""), "location": h.get("LOCATION", "")})
    except OSError:
        pass
    finally:
        s.close()
    return res


def mdns(seconds=3):
    """Optional: needs `pip install zeroconf`. Returns {ip: name}"""
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return {}
    found = {}
    types = ["_http._tcp.local.", "_hap._tcp.local.", "_googlecast._tcp.local.", "_airplay._tcp.local.",
             "_rtsp._tcp.local.", "_hue._tcp.local.", "_esphomelib._tcp.local.", "_miio._udp.local."]

    class L:
        def add_service(self, zc, t, name):
            info = zc.get_service_info(t, name, 1500)
            if info:
                for a in info.parsed_addresses():
                    found[a] = name.split(".")[0]
        update_service = remove_service = lambda *a: None

    zc = Zeroconf()
    try:
        [ServiceBrowser(zc, t, L()) for t in types]
        time.sleep(seconds)
    finally:
        zc.close()
    return found


def classify(vendor, ports, info):
    text = (vendor + " " + info).lower()
    if 554 in ports or 8554 in ports or vendor in ("Hikvision", "Dahua") or "camera" in text or "ipcam" in text:
        return "camera"
    if "hue" in text:
        return "light"
    if vendor == "TP-Link":
        return "plug"
    if 8008 in ports or 8009 in ports or 1400 in ports or vendor in ("Sonos", "Google", "Amazon") or "chromecast" in text:
        return "media"
    if 1883 in ports or 8123 in ports or vendor == "Raspberry Pi":
        return "hub"
    if vendor == "Espressif" or 55443 in ports or 6668 in ports or 5683 in ports:
        return "sensor"
    return "other"


def run_scan():
    if scan["running"]:
        return
    scan.update(running=True, progress=0, found=0, error=None)
    try:
        my_ip, net = local_subnet()
        hosts = [str(h) for h in net.hosts()]
        alive = {}

        def probe(ip):
            ports = open_ports(ip)
            up = bool(ports) or ping(ip)
            scan["progress"] += 1
            return ip, up, ports

        with cf.ThreadPoolExecutor(64) as ex:
            for ip, up, ports in ex.map(probe, hosts):
                if up:
                    alive[ip] = ports
        scan["progress"] = len(hosts)
        arp, up_nodes, names = arp_table(), ssdp(), mdns()
        now = int(time.time())
        for ip, ports in alive.items():
            mac = arp.get(ip, "")
            vendor = OUI.get(mac[:8], "")
            info = " ".join(filter(None, [up_nodes.get(ip, {}).get("server", ""), names.get(ip, "")]))
            try:
                host = socket.gethostbyaddr(ip)[0]
            except OSError:
                host = ""
            key = mac or ip
            with lock:
                d = devices.get(key) or devices.get(next((k for k, v in devices.items() if v["ip"] == ip), ""), None)
                if d is None:
                    d = {"id": key, "name": names.get(ip) or host or vendor or ip, "type": classify(vendor, ports, info),
                         "stream": "", "manual": False, "hidden": False}
                    devices[key] = d
                d.update(ip=ip, mac=mac, vendor=vendor, ports=ports, info=info.strip(), host=host, online=True, last_seen=now)
        with lock:
            for d in devices.values():
                if d["ip"] not in alive and not d.get("manual"):
                    d["online"] = False
            scan["found"] = len(alive)
        save()
        scan["last"] = int(time.time())
    except Exception as e:
        scan["error"] = str(e)
    finally:
        scan["running"] = False


def heartbeat():
    while True:
        time.sleep(30)
        for d in list(devices.values()):
            ports = d.get("ports") or [80]
            try:
                d["online"] = bool(open_ports(d["ip"], ports[:3], 0.6)) or ping(d["ip"])
                if d["online"]:
                    d["last_seen"] = int(time.time())
            except Exception:
                pass


def auto_scan():
    while True:
        run_scan()
        time.sleep(AUTO_SCAN_SECONDS)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/api/devices":
            return self.send({"devices": list(devices.values()), "scan": scan})
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self.send(f.read(), ctype="text/html; charset=utf-8")
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/scan":
            threading.Thread(target=run_scan, daemon=True).start()
            return self.send({"started": True})
        if self.path == "/api/devices":  # add manually (cameras included)
            b = self.body()
            ip = (b.get("ip") or "").strip()
            if not ip:
                return self.send({"error": "IP address is required"}, 400)
            did = "manual-" + uuid.uuid4().hex[:8]
            d = {"id": did, "name": b.get("name") or ip, "ip": ip, "mac": "", "vendor": "", "ports": [],
                 "type": b.get("type", "other"), "stream": b.get("stream", ""), "info": "", "host": "",
                 "manual": True, "hidden": False, "online": bool(open_ports(ip, [80, 443, 554, 8080], 0.6)) or ping(ip),
                 "last_seen": int(time.time())}
            devices[did] = d
            save()
            return self.send(d)
        self.send({"error": "not found"}, 404)

    def do_PUT(self):
        did = self.path.rsplit("/", 1)[-1]
        if did not in devices:
            return self.send({"error": "not found"}, 404)
        b = self.body()
        devices[did].update({k: b[k] for k in ("name", "type", "stream", "ip", "hidden") if k in b})
        save()
        self.send(devices[did])

    def do_DELETE(self):
        devices.pop(self.path.rsplit("/", 1)[-1], None)
        save()
        self.send({"ok": True})


if __name__ == "__main__":
    load()
    threading.Thread(target=auto_scan, daemon=True).start()
    threading.Thread(target=heartbeat, daemon=True).start()
    print(f"Dashboard running: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
