# Signal Delivery Setup for Garmin Motivation Cron Jobs

## Current Setup (2026-06-10)

The Garmin Motivation skill has two cron jobs delivering to **Signal** (not WhatsApp):

| Job | Schedule | Script |
|-----|----------|--------|
| `garmin-daily` | Daily 07:00 | `daily_motivation.py` |
| `garmin-weekly` | Sunday 10:00 | `weekly_recap.py` |

Both configured with `deliver: "signal"` in cron job definition.

## Prerequisites for Signal Delivery

1. **signal-cli daemon running** on `127.0.0.1:8080` (HTTP mode)
   ```bash
   signal-cli -a +436****4567 daemon --http 127.0.0.1:8080
   ```
   Should be managed as a LaunchAgent for autostart.

2. **Signal account registered/linked** with signal-cli
   ```bash
   # Check registration
   signal-cli -a +436****4567 listDevices
   
   # If not registered: link via QR code
   signal-cli -a +436****4567 link --name "Hermes Gateway"
   ```

3. **Hermes Gateway configured** with correct env vars in `~/.hermes/.env`:
   ```
   SIGNAL_HTTP_URL=http://127.0.0.1:8080
   SIGNAL_ACCOUNT=+436****4567
   ```

4. **Gateway running as LaunchAgent** (not Desktop app):
   ```bash
   # Status
   launchctl list | grep hermes
   
   # Restart (must be external, not from inside gateway)
   launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway
   ```

## Known Issues

- **SSE Reconnect Loop**: If gateway.log shows constant `Signal SSE: connected` spam, the Signal session is stale. Fix: restart gateway externally + ensure signal-cli daemon is healthy.
- **Gateway Restart Blocked Internally**: `hermes gateway restart` called from inside a gateway session is refused. Must use `launchctl kickstart` or SSH.
- **Signal Not Registered**: Empty `~/.local/share/signal-cli/data/accounts.json` means no account linked. Run linking flow.

## Verification Commands

```bash
# Test signal-cli daemon health
curl http://127.0.0.1:8080/api/v1/check

# Test direct send via signal-api
curl -X POST http://127.0.0.1:8080/v1/send \
  -H "Content-Type: application/json" \
  -d '{"message": "Test from Hermes", "number": "+436****4567", "recipients": ["+436****4567"]}'

# Check gateway logs for Signal activity
tail -f ~/.hermes/logs/gateway.log | grep -i signal
```