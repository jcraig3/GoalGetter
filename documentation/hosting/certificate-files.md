# Your own certificate files

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

For a certificate from your IT department's authority, or one you bought.

In **Settings → Hosting → Change**:

1. **How:** **A certificate from IT**.
2. **Set up:** **Name**, the name the certificate is for, e.g.
   `goalgetter.company.com`. Upload the certificate (including any
   intermediate certificates) and its private key, as PEM files. They're
   checked (the key must match, the certificate not expired) and saved as
   `volumes/certs/cert.pem` and `key.pem`. **Check** confirms the certificate
   covers the name and the name points at this server.
3. **Switch over**, then **Keep** once `https://…` opens. No restart, and the
   old address keeps working until you keep it
   ([Changing it safely](../20-hosting.md#changing-it-safely)).

**Or by hand:** copy the two files into the GoalGetter folder as
`volumes/certs/cert.pem` and `volumes/certs/key.pem`, then in `.env`:

```bash
HTTPS_HOST=goalgetter.company.com      # the name the certificate is for
HTTPS_CERTIFICATE=files
```

The app picks it up within half a minute.

GoalGetter does not renew these. Before they expire, upload new ones with
**Replace** (Change → A certificate from IT), or replace both files and run
`docker compose restart https`.
