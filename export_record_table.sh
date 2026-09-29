#!/bin/bash
# Export the "Record" table to a CSV file.
# Usage: ./export_record_table.sh              (writes to record_YYYYMMDD_HHMMSS.csv, exports "records")
#        ./export_record_table.sh out.csv      (writes to a specific filename)
#        ./export_record_table.sh out.csv "other_table"   (export a different table)

TABLE="${2:-records}"
OUTFILE="${1:-record_$(date '+%Y%m%d_%H%M%S').csv}"

# Load DATABASE_PUBLIC_URL from the .env next to this script.
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

echo "Exporting \"$TABLE\" to $OUTFILE ..."

psql "$DATABASE_PUBLIC_URL" -c "\copy \"$TABLE\" TO '$OUTFILE' WITH CSV HEADER"

if [ $? -eq 0 ]; then
    echo "Done. Rows written to $OUTFILE:"
    wc -l < "$OUTFILE"
else
    echo "Export failed." >&2
    exit 1
fi