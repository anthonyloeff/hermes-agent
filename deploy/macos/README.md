# macOS Jill-Kelly-Angel A2A pilot

## Trusttopologie

- Jill vertrouwt Kelly en Angel.
- Kelly vertrouwt alleen Jill.
- Angel vertrouwt alleen Jill.
- Kelly en Angel hebben geen directe catalogus-, credential- of trustrelatie.
- Iedere richting gebruikt een uniek peercredential dat alleen in het betreffende profielbestand `.env` staat.

## Runtime

Run `scripts/bootstrap-anthony-macos-runtime.sh` before installing services.

## Service installation

Copy the two plists to `~/Library/LaunchAgents/`, validate with `plutil -lint`, then use `launchctl bootstrap gui/$(id -u) <plist>`.

The profile `.env` files are intentionally not tracked. They contain unique per-direction A2A credentials and must remain mode `0600`.

## Tailscale Serve

- Jill: HTTPS 8443 to `http://127.0.0.1:19900`
- Kelly: HTTPS 8444 to `http://127.0.0.1:19901`
- Angel: HTTPS 8445 to `http://127.0.0.1:19902`
- Mission Control remains on HTTPS 443.
- All routes are tailnet-only. Never use Funnel for this pilot.

## Rollback

1. `tailscale serve --https=8443 off`
2. `tailscale serve --https=8444 off`
3. `tailscale serve --https=8445 off`
4. `launchctl bootout gui/$(id -u)/ai.litic.hermes-a2a-jill`
5. `launchctl bootout gui/$(id -u)/ai.litic.hermes-a2a-kelly`
6. `launchctl bootout gui/$(id -u)/ai.litic.hermes-a2a-angel`
7. Remove only the three `ai.litic.hermes-a2a-*.plist` files.
8. Do not reset all Tailscale Serve configuration, because HTTPS 443 belongs to Mission Control.
