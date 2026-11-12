# Install Milo

This guide sets up Milo on a Mac and connects an iPhone to it. It takes about 30 minutes.

## What you need

- A Mac with Apple silicon that stays on. Milo runs on the Mac.
- An iPhone, or a phone or laptop with a modern browser.
- A Claude Pro or Max plan. Milo uses Claude Code through your plan.
- [Homebrew](https://brew.sh) and a free [Tailscale](https://tailscale.com) account.

## 1. Install the tools

```sh
brew install uv node block-goose-cli whisper-cpp ffmpeg
brew install --cask google-chrome tailscale-app
curl -fsSL https://claude.ai/install.sh | bash
npm install -g @agentclientprotocol/claude-agent-acp
```

Then set goose to use Claude Code. Put these lines in `~/.config/goose/config.yaml`:

```yaml
GOOSE_PROVIDER: claude-acp
GOOSE_MODEL: claude-sonnet-5-5
```

## 2. Get the code and start Milo

```sh
git clone https://github.com/YOUR_GITHUB_USER/milo ~/Documents/Milo/milo
cd ~/Documents/Milo/milo && ./start.sh
```

The first start downloads the speech models (about 900 MB), asks you to sign in to Claude, and prints a one-tap URL. Start Milo from the Terminal app, not over SSH. Over SSH, Milo cannot read the macOS Keychain.

## 3. Connect your phone

1. Sign in to Tailscale on the Mac and on the iPhone, with the same account.
2. In the [Tailscale admin console](https://login.tailscale.com/admin/dns), turn on MagicDNS and HTTPS certificates.
3. Stop Milo (Ctrl+C) and run `./start.sh` again. It prints the one-tap URL with your Mac's Tailscale name.
4. On the iPhone, open the URL in Safari. Tap Share > Add to Home Screen.
5. In Milo, open Settings > Notifications and tap Turn on.

Do not share the one-tap URL. It holds your access token.

## 4. Google accounts (optional)

1. In console.cloud.google.com, make a project. Enable the Gmail, Google Calendar and Google Drive APIs.
2. Set up the OAuth consent screen as External, then publish the app (In production). In Testing mode, Google signs you out every 7 days.
3. Make an OAuth client ID of the type Desktop app.
4. In Milo, open Settings > Google accounts. Paste the client ID and secret, then connect each account.

## Keep Milo running

```sh
nohup ./start.sh >> ~/Library/Logs/milo.log 2>&1 &
```

After a change to a Python file, stop this process and start it again. Changes in `web/` load on the phone automatically.

## Problems

| Problem | What to do |
|---|---|
| "Not logged in" or Keychain errors | Start Milo from the Terminal app, not over SSH. |
| The phone cannot connect | Make sure that Tailscale is on, on the Mac and on the phone. |
| No microphone on the phone | Use the `https://` URL. iOS blocks the microphone on `http://`. |
| You lost the one-tap URL | Run `./start.sh` again. |
| Google signs you out every week | Publish the OAuth app (step 4.2), then connect the accounts again. |
