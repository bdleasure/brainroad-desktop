# BrainRoad for Hermes

Tell your computer what you need done. BrainRoad works inside [Hermes Desktop](https://hermes-agent.nousresearch.com/desktop),
the open-source agent app from Nous Research, on your own Windows PC or Mac:

- **Computer help** — diagnose a printer, sound, Wi-Fi, app or settings problem, keep a way to undo
  the change, then repeat what you were trying to do to show it works.
- **Browser work** — look things up, fill in forms, download and upload files in a visible browser,
  with sign-ins and verification left to you.
- **Coding** — change and test a real project on your computer and show the exact diff.
- **Phone link (optional)** — reach Hermes on this computer from your phone's browser after you
  approve it once with a BrainRoad account.

This is a **preview**. See [what has been verified](https://app.brainroad.com/desktop/) before relying on it.

## Install

1. Install Hermes Desktop from [Nous Research](https://hermes-agent.nousresearch.com/desktop) and
   finish its first-run setup, including the model connection you choose.
2. Click **[Add BrainRoad to Hermes](hermes://plugin/install?repo=bdleasure/brainroad-desktop&enable=1)**.
   Hermes shows the repository and exact commit; review it and choose **Install**.
   From a terminal instead: `hermes plugins install bdleasure/brainroad-desktop --enable`.
3. Open **BrainRoad** in Hermes' sidebar and choose what you need done.

Hermes installs plugins into the profile you are using. BrainRoad works with whatever model you
picked in Hermes, including a model running on this computer.

## What it adds and what it does not change

| Added | Where |
| --- | --- |
| Four skills: `brainroad:computer-help`, `browser-work`, `code-work`, `first-task` | `skills/` |
| A short set of working rules in each new chat (about 1,200 characters) | `__init__.py` |
| The BrainRoad page, a palette command and a phone status chip | `desktop/plugin.js` |
| The phone link, off until you pair it | `dashboard/` |

BrainRoad does **not** change Hermes' permissions, approvals, tools, model, memory or browser.
It does not copy browser cookies, read other apps' logins, install startup items or open a port.
Hermes and the BrainRoad plugin run with your own user account's access; a plugin is not a sandbox.

## Where your data goes

- Tools run on the computer where the Hermes gateway runs.
- Your **model provider** receives what the agent sends it (your requests, and text it reads from
  files and pages). A model on this computer keeps that local; a hosted model does not.
- With the **phone link** on, your phone's requests travel through BrainRoad's servers to this
  computer over one outbound connection. BrainRoad routes that traffic and checks that you own the
  computer; it does not store your chats, files or screen. Hermes still asks your phone to sign in,
  through a BrainRoad sign-in that only this computer's owner can complete.
- While the phone link is on, BrainRoad's service and your BrainRoad account are part of what
  protects this computer: whoever controls either could reach Hermes here, which can run commands
  as you. Use a strong sign-in for BrainRoad and turn the link off when you don't need it.
- **Turn phone access off** in the BrainRoad page: the connection closes at once. **Disconnect**
  also forgets this computer's credential, asks BrainRoad to revoke it, and restores your previous
  Hermes Web Access settings.

## Remove it

Hermes → **Capabilities → Plugins → BrainRoad → Uninstall**, or `hermes plugins remove brainroad`.
Disconnect the phone link first if you paired it. Your Hermes chats, files and settings stay.

## Develop and verify

```bash
python3 -m unittest discover -s tests          # package checks (phone link tests need websockets + httpx)
python3 build.py --output dist                 # reproducible source ZIP + checksum manifest
python3 verify_upstream.py --hermes-source PATH --scratch DIR   # load into a real Hermes checkout
```

The phone link talks to `https://app.brainroad.com` (`BRAINROAD_URL` overrides it for tests; only
loopback may use plain HTTP).

## License

MIT — see [LICENSE](LICENSE). Third-party software this works with is listed in [NOTICE.md](NOTICE.md).
