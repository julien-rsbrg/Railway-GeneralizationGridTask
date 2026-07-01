#!/bin/bash
set -a          # auto-export every variable that gets defined
source .env     # load the file
set +a          # stop auto-exporting

pip install -r requirements.txt
python app.py        # serves on http://localhost:8000