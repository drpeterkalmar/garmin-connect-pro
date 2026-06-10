# Cron Job Setup for Garmin Motivation

## Daily Motivation (7:00 AM)
Sends today's motivational message to WhatsApp group "Hermi Status".

```bash
hermes cronjob create --name garmin-daily \
  --schedule "0 7 * * *" \
  --prompt "Run ~/.hermes/skills/leisure/garmin-connect-motivation/scripts/daily_motivation.py and send output to WhatsApp group 'Hermi Status'" \
  --skills garmin-connect-motivation
```

## Weekly Recap (Sunday 10:00 AM)
Sends weekly summary to WhatsApp group "Hermi Status".

```bash
hermes cronjob create --name garmin-weekly \
  --schedule "0 10 * * 0" \
  --prompt "Run ~/.hermes/skills/leisure/garmin-connect-motivation/scripts/weekly_recap.py and send output to WhatsApp group 'Hermi Status'" \
  --skills garmin-connect-motivation
```

## List / Manage Cron Jobs
```bash
hermes cronjob list
hermes cronjob pause --job_id <id>
hermes cronjob resume --job_id <id>
hermes cronjob remove --job_id <id>
```

## Delivery Target
- Group: "Hermi Status" (WhatsApp)
- Uses Hermes' `send_message` tool internally
- Ensure WhatsApp gateway is running (Desktop App on Mac mini)

## Testing Before Cron
```bash
cd ~/.hermes/skills/leisure/garmin-connect-motivation
python scripts/daily_motivation.py
python scripts/weekly_recap.py
```
Verify output looks correct before enabling cron.