# Experiment data backend (Flask + Railway Postgres)

Receives trial data POSTed from a Unity WebGL build and stores it in Postgres.
Exposes a CSV export for analysis.
Meant to be deployed on Railway app.


## Endpoints
- `POST /data` — receives one trial `{...}` or a batch `[{...}, ...]` need X-API-Key in header with value API_KEY
- `GET  /export` — downloads all data as one CSV (add `?token=...` and API_KEY after) 
- `GET  /health` — quick liveness check


## Run locally
```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://user:pass@localhost:5432/yourdb"
python app.py        # serves on http://localhost:8000
```
