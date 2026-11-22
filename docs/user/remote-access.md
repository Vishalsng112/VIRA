# Remote access

VIRA supports three connection paths:

| Path | Extra app on phone | Public | Best for |
|---|---|---|---|
| **Cloudflare named tunnel** | No | Yes, HTTPS | Default remote access |
| **Local network** | No | No | Home Wi-Fi |
| **Tailscale private** | Yes | No | Advanced/private-only setups |

Pairing links carry every available endpoint. VIRA Link tries the Cloudflare
URL first when it is configured, and automatically falls back to the LAN or
Tailscale address if the public URL cannot be reached.

The default configuration is:

```yaml
access:
  provider: cloudflare
  cloudflare:
    enabled: true
    public_url: null
  lan:
    enabled: true
```

If Cloudflare is not configured yet, pairing falls back to the LAN address and
shows a warning instead of generating an unreachable QR code.

---

## 1. Cloudflare named tunnel

A named tunnel is **not** the temporary `trycloudflare.com` quick tunnel. The
named tunnel keeps the same hostname across restarts.

### Requirements

- A domain added to Cloudflare (nameservers pointed at Cloudflare)
- `cloudflared` on the VIRA server
- The tunnel service running under systemd

The Cloudflare tunnel service is free. The domain is the only cost.

### Install and create the tunnel

On Linux:

```bash
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

cloudflared tunnel login
cloudflared tunnel create vira
cloudflared tunnel route dns vira vira.example.com
```

`tunnel login` opens a browser window for your Cloudflare account. Copy the
tunnel ID printed by `tunnel create`.

### Configure the tunnel

Create `/etc/cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: vira.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Install and start the service:

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

Test from outside your network:

```bash
curl https://vira.example.com/health
```

### Tell VIRA about the tunnel

```yaml
access:
  provider: cloudflare
  cloudflare:
    enabled: true
    public_url: https://vira.example.com
    tunnel_name: vira
    binary: cloudflared

auth:
  https_only: true   # only when you do not use plain-HTTP LAN access
```

If you use the LAN fallback over plain HTTP, leave `https_only: false` and keep
the LAN trusted. The Cloudflare tunnel itself is always HTTPS.

Reload VIRA or restart the server. The dashboard **Devices → Remote access**
card should now show **Cloudflare named tunnel** as the pairing address.

The phone needs only VIRA Link. No Cloudflare or VPN app is installed on the
phone.

### Security

A public hostname is scanned continuously. Before enabling it:

- set a strong administrator password
- keep first-time setup (`/setup`) closed
- keep login and pairing endpoints rate-limited
- use HTTPS only
- monitor failed logins
- do not publish the server before the administrator account exists

For stronger protection, put **Cloudflare Access** in front of the dashboard
and API. VIRA authentication remains required inside the tunnel.

---

## 2. Local network access

VIRA automatically detects a private IPv4 address:

```text
http://192.168.1.4:8000
```

It ignores loopback, Docker, Tailscale and link-local interfaces. Pairing links
include this address so a phone on the same Wi-Fi can connect even if the public
tunnel is unavailable.

Configuration:

```yaml
access:
  lan:
    enabled: true
    scheme: http
    address: null      # auto-detect the private LAN address
    port: null         # defaults to the dashboard port
    interface: null    # optional, e.g. enp6s0
```

### Docker

Inside a Docker bridge network, the detected address is the container address,
not the host LAN address. Set the host values explicitly:

```yaml
access:
  lan:
    address: 192.168.1.4
    port: 8000
```

The port must be the published host port, not the container port.

### Endpoint fallback

A pairing link can contain:

```text
https://vira.example.com
http://192.168.1.4:8000
```

VIRA Link stores both. If the public URL is unreachable, it retries the LAN
address; if the LAN address is unreachable, it retries the public URL. This
makes pairing at home fast while keeping remote access working.

---

## 3. Verify pairing

1. Open **Devices** in the dashboard.
2. Confirm **Remote access** shows the Cloudflare URL.
3. Generate a pairing code.
4. Scan it with VIRA Link on Android, or paste the code/link on Linux.

The QR contains the public URL and the LAN fallback. No extra application is
required on the phone.

---

## 4. Optional: Tailscale private access

Tailscale is kept as an advanced provider. It is **not** required for the
default setup, and ordinary users should not need the Tailscale app.

Use it only when you explicitly want a private tailnet and accept installing
Tailscale on every client.

Install and connect on the server:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname vira-server
```

The dashboard can run the login flow under **Devices → Remote access → Manage
Tailscale**, including browser/QR login and an auth-key fallback.

Then select it:

```yaml
access:
  provider: tailscale
```

---

## 5. Provider order

`access.provider` controls the primary address:

| Value | Primary | Fallbacks included in the QR |
|---|---|---|
| `cloudflare` | Cloudflare named tunnel | LAN, Tailscale, dashboard |
| `auto` | Cloudflare, then LAN, then Tailscale | All available |
| `lan` | Local network | Cloudflare, Tailscale, dashboard |
| `tailscale` | Tailscale private | LAN, Cloudflare, dashboard |
| `request` | Dashboard address | Other available providers |
| `custom` | `access.public_url` | Other available providers |

## Adding another provider

Providers live in `vira/access/providers.py` and are registered by
`vira/access/resolver.py`. A provider needs:

- a `kind` and `label`
- a `status(request, settings)` method returning an `AccessEndpoint`

Then users select it with `access.provider`.

See the [security overview](security.md) before exposing any public endpoint.
