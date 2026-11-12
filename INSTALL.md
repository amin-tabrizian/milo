# Install Milo

This guide sets up Milo on a Mac and connects an iPhone to it. It takes about 30 minutes. Most of that time is downloads.

## What you need

- A Mac with Apple silicon that stays on. Milo runs on the Mac. The phone only shows the app.
- An iPhone (or any phone or laptop with a modern browser).
- A Claude Pro or Max plan. Milo uses Claude Code through your plan, not an API key.
- [Homebrew](https://brew.sh).
- A free [Tailscale](https://tailscale.com) account. It lets your phone reach the Mac from anywhere, and only you can reach it.
- Optional: a Google Cloud project, if you want Gmail, Calendar and Drive (see [Google accounts](#google-accounts)).

## 1. Install the tools

```sh
brew install uv node block-goose-cli whisper-cpp ffmpeg
brew install --cask google-chrome tailscale-app
curl -fsSL https://claude.ai/install.sh | bash                # Claude Code CLI
npm install -g @agentclientprotocol/claude-agent-acp          # lets goose drive Claude Code
```

Versions known to work: goose 1.55, claude-agent-acp 0.93, Claude Code 2.1.

## 2. Set goose to use Claude Code

Run `goose configure` and select the `claude-acp` provider, or put these two lines in `~/.config/goose/config.yaml`:

```yaml
GOOSE_PROVIDER: claude-acp
GOOSE_MODEL: claude-sonnet-5-5
```

## 3. Get the code

```sh
mkdir -p ~/Documents/Milo
git clone https://github.com/YOUR_GITHUB_USER/milo ~/Documents/Milo/milo
cd ~/Documents/Milo/milo
```

Keep the code in `~/Documents/Milo/milo`. Milo works in `~/Documents/Milo` (its `Library` and `Instructions` folders go there).

## 4. Start Milo

```sh
./start.sh
```

The first start does these steps:

1. It downloads the speech models (about 900 MB) into `models/`.
2. It installs the Python packages.
3. It asks you to sign in to Claude. Milo has its own Claude profile in `data/claude`, apart from your other Claude sessions.
4. It makes `data/config.json` with a new access token, and prints a **one-tap URL**.

Start Milo from the Terminal app on the Mac, not over SSH. Over SSH, Claude Code and the saved accounts cannot read the macOS Keychain.

## 5. Connect your phone

1. Open the Tailscale app on the Mac and sign in. In its settings, install the command line tool (`start.sh` uses `tailscale`).
2. Install Tailscale on the iPhone. Sign in with the same account as on the Mac.
3. In the [Tailscale admin console](https://login.tailscale.com/admin/dns), turn on **MagicDNS** and **HTTPS certificates**. iOS needs HTTPS for the microphone and for push alerts.
4. Stop Milo (Ctrl+C) and run `./start.sh` again, so that it publishes Milo on your tailnet. It prints the one-tap URL with your Mac's Tailscale name.
5. On the iPhone, open the one-tap URL in Safari. Tap **Share > Add to Home Screen**, then open Milo from the home screen.
6. In Milo, open **Settings > Notifications** and tap **Turn on**.

The one-tap URL holds your access token. Anyone with that URL can control Milo on your Mac. Do not share it.

## 6. Optional features

| Feature | How to turn it on |
|---|---|
| Gmail, Calendar, Drive | See [Google accounts](#google-accounts) below. |
| X feed | Tap the globe button to open Milo's browser, and log in to x.com once. Then open the Feed tab and tap Refresh. |
| Hey Siri | **Settings > Hey Siri** shows the Shortcut steps. |
| Saved logins | **Settings > Accounts**. Passwords stay in the Mac's Keychain; the AI never sees them. |

## Google accounts

1. Open console.cloud.google.com and create a project named Milo.
2. APIs & Services > Library: enable Gmail API, Google Calendar API and Google Drive API.
3. OAuth consent screen: External. Add each Google email you want in Milo as a test user.
4. Credentials > Create credentials > OAuth client ID > Desktop app.
5. In Milo: Settings > Google accounts. Paste the Client ID and secret, then Connect account for each email.

Tokens for each account are kept in `data/google-credentials/` (mode 700). The client secret is in the Keychain.

## 7. First things to try

- "Remember that I prefer short answers."
- "Every weekday at 8, brief me on my calendar and unread email."
- "Add a goal: run a half marathon in March."
- Hold the mic button and talk, or tap the Milo avatar for hands-free voice mode.
- Press Stop during a long task. Milo stops the work on the Mac, not only on the screen.

## Keep private

- `data/` holds your chats, memory, access token, Google tokens and browser profile. Git ignores it. Never share it.
- Milo listens only on `127.0.0.1`. Tailscale publishes it only to your own devices.

## Run Milo all the time

`./start.sh` runs in the front of the Terminal window. To keep it running after you close the window:

```sh
nohup ./start.sh >> ~/Library/Logs/milo.log 2>&1 &
```

To restart after a change to a Python file, stop that process and run the command again. Changes in `web/` load on the phone by themselves.

## Tests

```sh
uv run pytest                           # unit and API tests (seconds)
uv run pytest -m e2e                    # real headless Chrome, no AI model (about a minute)
uv run pytest -m agent                  # real tasks through goose and Claude (uses your plan)
uv run python tests/live/run.py         # live behavior suite: 31 cases (about 10 minutes, uses your plan)
```

Run the Keychain tests from the Terminal app, not over SSH.

## For developers

- `README.md`: what each feature does, and a map of the files.
- `CLAUDE.md`: the rules for changes to the code (read it before you change Milo).
- `BEHAVIOR.md`: each behavior problem that was found, and how it was fixed. It is private (git ignores it). Start it from `BEHAVIOR.example.md`.

## Troubleshooting

| Problem | What to do |
|---|---|
| "Not logged in" or Keychain errors | Start Milo from the Terminal app on the Mac, not over SSH. |
| The phone cannot connect | Make sure Tailscale is on, on the Mac and on the phone, with the same account. |
| No microphone on the phone | Use the `https://` Tailscale URL. iOS blocks the microphone on plain `http://`. |
| You lost the one-tap URL | Run `./start.sh` again. It prints the URL each time. |
| You need a new access token | Delete `token` from `data/config.json` and restart. |
| You moved the folder | Sign in to Claude again: the sign-in belongs to the folder path. |
