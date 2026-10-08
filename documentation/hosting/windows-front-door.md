# The Windows front door

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

For a **Windows server running Docker Desktop** that should limit wrong
passwords **per device**. Docker Desktop hides every device's address from
anything inside Docker (see [Seeing each device](../20-hosting.md#seeing-each-device)). This
runs the HTTPS part, Caddy, **on Windows itself as a service** instead, in
front of Docker. It sees each device first and passes its address on.

Everything else is the same as options B–E: the same names, the same three
kinds of certificate, the same Microsoft sign-in steps, and the same TV
address.

1. **Choose the name and certificate first**, exactly as in
   [B](own-certificate.md) (your own certificate),
   [C](company-domain.md) (your domain) or
   [D](duckdns.md) (DuckDNS): in Settings → Hosting → Change (**Keep** it
   before the next step), or in `.env` (`HTTPS_HOST`, `HTTPS_CERTIFICATE`, and
   for Let's Encrypt the `DNS_` lines).
   While the front door is in place, Settings → Hosting says "HTTPS is handled
   by" it, and Caddy in Docker serves nothing.
2. **Run the installer** from the GoalGetter folder, in PowerShell opened
   **as administrator**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\install-front-door.ps1
   ```
   It downloads Caddy for Windows into `windows\caddy\` and checks the
   configuration. It moves Docker's ports to this computer only
   (`docker-compose.frontdoor.yml`, added to `COMPOSE_FILE` for you), so
   nothing on the network can bypass the front door. It installs and starts
   the **GoalGetterHTTPS** service, which starts with Windows and restarts if
   it stops, and waits for it to answer. **Only then** does it set
   `HTTPS_FRONT_DOOR=windows`, which sends everybody through it; if anything
   fails first, it puts everything back as it was. Finally it opens the
   firewall for the HTTPS, HTTP and TV ports. GoalGetter itself also keeps
   port 8080 a full app while the front door isn't answering.
3. **Check it.** Open `https://<your name>` from a phone or another PC, sign
   in, and go to **Settings → Hosting**. **You appear as** should show that
   device's own address, not "Unknown".
4. **Trust the certificate** on each device, as in
   [B step 3](own-certificate.md#3-trust-the-certificate-on-each-device) (option B only). The
   root certificate is at `http://<your name>/goalgetter-root.crt`. The
   server itself is a device like any other: the front door never adds its
   authority to Windows by itself.

To change the name or certificate later, edit `.env` and run
`Restart-Service GoalGetterHTTPS`. To go back to HTTPS inside Docker, run the
installer with `-Remove`. HTTPS then follows Settings → Hosting again.

TVs keep using `http://<server>:8080/pair`. A channel's network list still
can't be checked with the front door, because a TV's address goes through
Docker's plain port. Leave it empty.
