# HTTPS with GoalGetter's own certificate

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

**The base option.** Free, works with no internet connection and no domain.
GoalGetter runs its own small certificate authority, which issues and renews
the certificate automatically. The one catch: each device has to trust that
authority once. On company PCs, IT can do that for everybody in one step.

## 1. Pick a name, and point it at the server

People will type this name. Short, and ending in `.internal`, is a good
choice: `goals.internal`. That ending is reserved for private networks and
never clashes with a real website.

Make the name lead to the server's address (here `192.168.1.149`). Use
**whichever one of these you have**:

- **Windows DNS server** (common in an Active Directory domain): DNS Manager →
  your zone → New Host (A) → name `goals`, IP `192.168.1.149`. A name inside your
  AD domain, like `goals.corp.acme.com`, works just as well.
- **Your router**, usually under "DNS", "Local DNS" or "Static hosts".
- **To test on one computer only**, add a line to its hosts file
  (`C:\Windows\System32\drivers\etc\hosts`, or `/etc/hosts` on a Mac):
  ```
  192.168.1.149   goals.internal
  ```

You can also skip the name and use the IP address itself, `192.168.1.149`, as
the name. A name is still better. If the server ever moves,
you change one DNS record instead of every device.

## 2. Switch over

In **Settings → Hosting → Change**:

1. **How:** **Your network**.
2. **Set up:** **Name** `goals.internal` (no `https://`, no port). **Check**
   confirms the name points at this server. (A name only in one computer's
   hosts file shows as not in DNS. That's only a warning: switch over all the same.)
3. **Switch over**, then **Keep** once `https://goals.internal` opens.

No restart. During the trial both addresses work, so nothing breaks while you
try it ([Changing it safely](../20-hosting.md#changing-it-safely)). Once kept,
`https://goals.internal` serves GoalGetter, `http://goals.internal` redirects
to it, and the plain address serves TVs only.

**"Doesn't open from this device yet"?** Usually this device doesn't trust
the certificate yet: download it from the link, trust it as in step 3, and
the check turns green.

**Or in `.env`**, picked up within half a minute:

```bash
HTTPS_HOST=goals.internal
HTTPS_CERTIFICATE=internal
```

On a new install, `setup.ps1 -Https goals.internal` (Windows) or
`sh setup.sh --https goals.internal` (Mac / Linux) sets `HTTPS_HOST` for you.

## 3. Trust the certificate on each device

Until a device trusts GoalGetter's authority, its browser shows a warning.
The authority's root certificate is at:

```
http://goals.internal/goalgetter-root.crt
```

The same link, with step-by-step instructions, is in **Settings → Hosting →
For devices and TVs** once you are signed in.

**Company PCs: let IT push it.** This is the normal way to roll out an
internal certificate, and afterwards nobody sees a warning:

- **Group Policy:** Computer Configuration → Policies → Windows Settings →
  Security Settings → Public Key Policies → **Trusted Root Certification
  Authorities** → Import → `goalgetter-root.crt`.
- **Intune:** Devices → Configuration → Create → Templates → **Trusted
  certificate**, upload the file, and assign it to your device groups. Make one
  profile per platform (Windows, macOS, iOS, Android).

**One device at a time:**

| Device | Steps |
|---|---|
| Windows | Open the file → Install Certificate → **Local Machine** → "Place all certificates in the following store" → **Trusted Root Certification Authorities** |
| Mac | Open the file → Keychain Access adds it to System → double-click it → Trust → **Always Trust** |
| iPhone / iPad | Open the link in **Safari** → Allow → Settings → Profile Downloaded → Install. Then **Settings → General → About → Certificate Trust Settings** → turn it on |
| Android | Settings → Security → Encryption & credentials → Install a certificate → **CA certificate** → pick the file |
| Firefox (any OS) | Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import |

The authority lives in `volumes/caddy/data`. **Keep that folder in your
backups.** As long as it survives, upgrades and rebuilds keep the same
authority, so nobody has to trust it again.

## 4. Microsoft sign-in

In the Azure portal: **App registrations** → your GoalGetter app →
**Authentication** → Web → **Add URI**:

```
https://goals.internal/api/auth/sso/callback
```

Settings → Hosting shows this exact address for your install. A
private name is fine: Microsoft only sends the browser to it and never
connects to it itself.

The other Microsoft features (directory sync, Excel, Teams, mail) use the
redirect addresses listed on the **Integrations** page. Add those too.

## 5. Check it

- `https://goals.internal` opens with a padlock and no warning.
- Settings → Hosting → **Web address** shows `https://goals.internal` as its
  default. Leave the field empty; HTTPS fills it in.
- Send yourself an invite. The link starts with `https://goals.internal`.
