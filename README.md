# TV Webhook Server

Place this on Render or VPS and run with:
`gunicorn webhook_mt5_server_with_db:app --bind 0.0.0.0:$PORT`

Files included:
- webhook_mt5_server_with_db.py
- requirements.txt
- .env.sample

Replace .env.sample -> .env and fill values.
