# Remote access with Tailscale

VIRA is **private-first**. By default, the server only uses the address you
opened the dashboard with. That works on a LAN but not from another network.

[Tailscale](https://tailscale.com/) gives each of your devices a private
WireGuard address in the same tailnet. VIRA uses that private address for
pairing and clients. **No port forwarding and no public URL are involved.**

Tailscale Funnel is a different feature and is **not** enabled or required.

## 1. Install Tailscale on the server

On Linux:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname vira-server
tailscale status
tailscale ip -4
```

Sign in to the same tailnet on the devices that will use VIRA:

- **Android:** install Tailscale from the Play Store, sign in, and leave the VPN
  enabled.
- **Linux:** install Tailscale and run `sudo tailscale up`.

Enable **MagicDNS** in the Tailscale admin console. It gives the server a stable
name such as:

```text
vira-server.tail1234.ts.net
```

Check that another device on the tailnet can reach the server:

```bash
curl http://vira-server.tail1234.ts.net:8000/health
```

## 2. Guided setup in the dashboard

You can let VIRA run the Tailscale login flow instead of using the CLI manually:

1. Open **Devices → Remote access**.
2. Click **Set up Tailscale**.
3. If Tailscale is installed but logged out, VIRA shows a **Tailscale login URL
   and QR code**. Open the link or scan the QR.
4. Sign in to Tailscale or create an account. VIRA polls the local Tailscale
   state and detects completion automatically.
5. When connected, the panel shows the tailnet address and the pairing QR uses
   it immediately.

VIRA never creates the Tailscale account itself. The signup/login step happens
in Tailscale's browser flow because it is third-party authentication.

The service user that runs VIRA needs permission to manage Tailscale. On Linux:

```bash
sudo tailscale set --operator=<vira-user>
```

If VIRA runs in Docker, run Tailscale on the host or use a sidecar container;
the container cannot authenticate the host's Tailscale node by itself.

### Auth key alternative

For headless hosts or Docker, expand **Use an auth key instead** in the panel.
Create an auth key in the Tailscale admin console and paste it into VIRA. VIRA
runs `tailscale up --auth-key=file:...` once using a temporary `0600` file, does
not store the key, never returns it in an API response, and removes the file
immediately. The key never appears in the process list.

## 3. Manual discovery

The default configuration also detects an existing Tailscale connection:

```yaml
access:
  provider: auto
  tailscale:
    enabled: true
    binary: tailscale
    scheme: http
    port: 8000
    hostname: null          # defaults to the machine hostname
    prefer_dns_name: true
    timeout_seconds: 2
```

How `auto` chooses an address:

1. `access.public_url` when set
2. the private Tailscale address
3. the address used to open the dashboard

The pairing dialog in the dashboard shows the resolved address under
**Devices → Remote access**. Generated pairing codes and QR links use that
address. The client does not need a special Tailscale mode; it connects to the
URL in the QR code.

On a working tailnet, the QR contains:

```text
http://vira-server.tail1234.ts.net:8000
```

## 4. Verify in VIRA

1. Open **Devices** in the dashboard.
2. Confirm **Remote access** shows **Tailscale private** and the expected URL.
3. Generate a pairing code.
4. Scan it with VIRA Link on Android, or paste the code/link on Linux.

The client must have Tailscale connected. If Tailscale is not detected, VIRA
falls back to the dashboard address and shows a warning instead of silently
generating an unreachable QR code.

## Optional: HTTPS with `tailscale serve`

Plain HTTP over the tailnet is already encrypted by WireGuard. If you want a
CA-valid HTTPS URL, publish only inside the tailnet:

```bash
sudo tailscale serve --bg 8000
```

Then configure VIRA to use the HTTPS address:

```yaml
access:
  tailscale:
    scheme: https
    port: 443
```

This is still private. Do **not** use `tailscale funnel` unless you explicitly
want to publish VIRA to the public internet.

## Restricting access

Tailscale ACLs can limit which tailnet users or devices may reach the VIRA
server port. VIRA authentication is still required after the network connection
is allowed.

For a small personal setup, the usual policy is:

- server and clients in the same tailnet
- no shared nodes
- no Funnel
- VIRA remains on its normal port, usually `8000`

## Adding another provider

Providers live in `vira/access/providers.py` and are registered by
`vira/access/resolver.py`. A new provider only needs:

- a `kind` and `label`
- a `status(request, settings)` method that returns an `AccessEndpoint` when
  reachable

Then users select it with:

```yaml
access:
  provider: my-provider
```

For a manually managed public endpoint such as a Cloudflare named tunnel, use
the built-in custom provider instead:

```yaml
access:
  provider: custom
  public_url: https://vira.example.com
```

Public exposure is an explicit choice, not the default. See the
[security overview](security.md) before publishing the server.
