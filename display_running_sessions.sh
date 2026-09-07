#!/bin/bash
# Live session monitor. Refreshes every REFRESH seconds.
# Usage: ./active_sessions.sh          (runs once)
#        ./active_sessions.sh --watch  (refreshes continually)

REFRESH=5   # seconds between refreshes in --watch mode

# Load DATABASE_PUBLIC_URL from the .env next to this script (once).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
else
    echo "No .env found next to this script." >&2
    exit 1
fi

if [ -z "$DATABASE_PUBLIC_URL" ]; then
    echo "DATABASE_PUBLIC_URL is not set in .env" >&2
    exit 1
fi

INNER="
    SELECT session_id, received_at,
           MIN(received_at) OVER (PARTITION BY session_id) AS first_reception,
           MAX(received_at) OVER (PARTITION BY session_id) - MIN(received_at) OVER (PARTITION BY session_id) AS active_for,
           data->>'data_type' AS dt, data->>'questionnaire_id' AS qid,
           data->>'trial' AS trial, data->>'predicted_value' AS predicted,
           data->>'actual_value' AS actual, data->>'item_index' AS item_index,
           data->>'subphase' AS subphase,
           COUNT(*) OVER (PARTITION BY session_id, data->>'questionnaire_id' ORDER BY received_at) AS q_running
    FROM records
"

OUTER_SELECT="
    SELECT DISTINCT ON (session_id)
           session_id,
           date_trunc('second', first_reception) AS first_reception,
           date_trunc('second', received_at) AS last_reception,
           date_trunc('second', active_for) AS active_for,
           dt AS last_data_type,
           CASE dt
               WHEN 'questionnaire'  THEN qid || ' #' || q_running::text
               WHEN 'exploration'    THEN CONCAT_WS(' ', 'trial', trial, ' - pred', predicted, ' - actual', actual)
               WHEN 'self_reference' THEN CONCAT_WS(' ', 'subphase', subphase, '- item', item_index)
           END AS last_step
    FROM ($INNER) sub
"

run_report() {
    echo "Updated: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=== All sessions ==="
    psql "$DATABASE_PUBLIC_URL" -c "$OUTER_SELECT ORDER BY session_id, received_at DESC;"
    echo "=== Only last 7 days ==="
    psql "$DATABASE_PUBLIC_URL" -c "$OUTER_SELECT WHERE first_reception > now() - interval '7 days' ORDER BY session_id, received_at DESC;"
}

if [ "$1" == "--watch" ]; then
    # Ctrl+C to stop.
    while true; do
        clear
        run_report
        sleep "$REFRESH"
    done
else
    run_report
fi