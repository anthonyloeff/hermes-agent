# macOS Jill-Kelly A2A pilot

## Runtime

Run `scripts/bootstrap-anthony-macos-runtime.sh` before installing services.

## Service installation

Copy the two plists to `~/Library/LaunchAgents/`, validate with `plutil -lint`, then use `launchctl bootstrap gui/$(id -u) <plist>`.

The profile `.env` files are intentionally not tracked. They contain unique per-direction A2A credentials and must remain mode `0600`.

## Tailscale Serve

- Jill: HTTPS 8443 to `http://127.0.0.1:19900`
- Kelly: HTTPS 8444 to `http://127.0.0.1:19901`
- Mission Control remains on HTTPS 443.
- All routes are tailnet-only. Never use Funnel for this pilot.

## Rollback

1. `tailscale serve --https=8443 off`
2. `tailscale serve --https=8444 off`
3. `launchctl bootout gui/$(id -u)/ai.litic.hermes-a2a-jill`
4. `launchctl bootout gui/$(id -u)/ai.litic.hermes-a2a-kelly`
5. Remove only the two `ai.litic.hermes-a2a-*.plist` files.
6. Do not reset all Tailscale Serve configuration, because HTTPS 443 belongs to Mission Control.
