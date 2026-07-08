import os
import io
import csv

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import psycopg
from psycopg.types.json import Jsonb

app = Flask(__name__)

# The WebGL build is served from this same app, so /data is same-origin and
# CORS is not strictly required; harmless to keep.
CORS(app)

DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY = os.environ.get("API_KEY")

BUILD_DIR = os.path.join(os.path.dirname(__file__), "webgl_build")

# The three kinds of data this experiment collects. A row whose data_type is
# not in this set is rejected, so a typo in the client can never silently
# create mislabeled records.
DATA_TYPES = {"questionnaire", "exploration", "self_reference"}


def get_conn():
    return psycopg.connect(DATABASE_URL)


def init_db():
    """
    One table holds every record type. data_type marks which kind each row is;
    data (JSONB) holds the type-specific fields, so new measures can be added
    in Unity without any schema change here.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id          BIGSERIAL   PRIMARY KEY,
                    session_id  TEXT        NOT NULL,
                    data_type   TEXT        NOT NULL,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    data        JSONB       NOT NULL
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_session "
                "ON records (session_id);"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_type "
                "ON records (data_type);"
            )
        conn.commit()


init_db()


# ---- Unity WebGL hosting -------------------------------------------------

def _add_unity_headers(resp, filename):
    name = filename
    if name.endswith(".br"):
        resp.headers["Content-Encoding"] = "br"
        name = name[:-3]
    elif name.endswith(".gz"):
        resp.headers["Content-Encoding"] = "gzip"
        name = name[:-3]

    if name.endswith(".wasm"):
        resp.headers["Content-Type"] = "application/wasm"
    elif name.endswith(".js"):
        resp.headers["Content-Type"] = "application/javascript"
    elif name.endswith(".data"):
        resp.headers["Content-Type"] = "application/octet-stream"
    return resp


@app.route("/")
def index():
    return send_from_directory(BUILD_DIR, "index.html")


@app.route("/<path:filename>")
def build_files(filename):
    resp = send_from_directory(BUILD_DIR, filename)
    return _add_unity_headers(resp, filename)


# ---- API -----------------------------------------------------------------

@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/data", methods=["POST"])
def receive_data():
    """
    Accepts one record {...} or a batch [{...}, ...]. Each record MUST carry a
    "data_type" field that is one of DATA_TYPES. The whole object is stored as
    JSONB; data_type is also pulled into its own column for easy filtering.
    """
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(force=True, silent=True)
    if payload is None:
        return jsonify({"error": "invalid or missing JSON"}), 400

    rows = payload if isinstance(payload, list) else [payload]

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    dtype = row.get("data_type")
                    if dtype not in DATA_TYPES:
                        return jsonify(
                            {"error": f"unknown or missing data_type: {dtype}"}
                        ), 400
                    cur.execute(
                        "INSERT INTO records (session_id, data_type, data) "
                        "VALUES (%s, %s, %s);",
                        (str(row.get("session_id", "unknown")), dtype, Jsonb(row)),
                    )
            conn.commit()
    except Exception as e:
        app.logger.error(f"DB insert failed: {e}")
        return jsonify({"error": "database error"}), 500

    return jsonify({"status": "saved", "rows": len(rows)}), 200


@app.route("/export", methods=["GET"])
def export_csv():
    """
    Download data as CSV. By default exports ALL types together (columns are
    the union across types, so many cells are blank). Pass ?type=exploration
    (or questionnaire / self_reference) for a clean single-type CSV.
    Protected by API_KEY: add &token=YOUR_KEY.
    """
    if API_KEY and request.args.get("token") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    dtype = request.args.get("type")   # optional filter
    if dtype is not None and dtype not in DATA_TYPES:
        return jsonify({"error": f"unknown type: {dtype}"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            if dtype:
                cur.execute(
                    "SELECT id, session_id, data_type, received_at, data "
                    "FROM records WHERE data_type = %s ORDER BY id;",
                    (dtype,),
                )
            else:
                cur.execute(
                    "SELECT id, session_id, data_type, received_at, data "
                    "FROM records ORDER BY id;"
                )
            rows = cur.fetchall()

    # Fixed columns first, then every key seen across the JSONB payloads.
    data_keys, seen = [], {"session_id", "data_type"}
    for _id, _sid, _dt, _ts, data in rows:
        for k in data:
            if k not in seen:
                seen.add(k)
                data_keys.append(k)

    fieldnames = ["id", "session_id", "data_type", "received_at"] + data_keys

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for _id, sid, dt, ts, data in rows:
        record = {"id": _id, "session_id": sid, "data_type": dt,
                  "received_at": ts.isoformat()}
        record.update(data)
        writer.writerow(record)

    fname = f"{dtype or 'all'}_export.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))