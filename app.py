import os
import io
import csv

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import psycopg
from psycopg.types.json import Jsonb

app = Flask(__name__)

# Still harmless to keep, but now that the WebGL build is served from THIS
# same app (see routes below), requests to /data are same-origin and CORS
# is no longer strictly required.
CORS(app)

DATABASE_URL = os.environ["DATABASE_URL"]
API_KEY = os.environ.get("API_KEY")

# Folder holding the Unity WebGL build output: it must contain index.html
# plus the Build/ and TemplateData/ folders exactly as Unity produced them.
BUILD_DIR = os.path.join(os.path.dirname(__file__), "webgl_build")


def get_conn():
    return psycopg.connect(DATABASE_URL)


def init_db():
    """Create the table once on startup. Idempotent, safe to re-run."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trials (
                    id          BIGSERIAL PRIMARY KEY,
                    session_id  TEXT        NOT NULL,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    data        JSONB       NOT NULL
                );
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_trials_session "
                "ON trials (session_id);"
            )
        conn.commit()


init_db()


# ---- Unity WebGL hosting -------------------------------------------------

def _add_unity_headers(resp, filename):
    """
    Unity WebGL builds may be Brotli/Gzip compressed (files ending .br/.gz).
    The browser only decompresses them if we send the right Content-Encoding,
    and it needs the correct Content-Type for the *underlying* file type
    (.wasm/.js/.data). If your build is uncompressed, the encoding part is
    simply skipped.
    """
    name = filename
    if name.endswith(".br"):
        resp.headers["Content-Encoding"] = "br"
        name = name[:-3]
    elif name.endswith(".gz"):
        resp.headers["Content-Encoding"] = "gzip"
        name = name[:-3]
    elif name.endswith(".zip"):
        resp.headers["Content-Encoding"] = "zip"
        name = name[:-4]

    if name.endswith(".wasm"):
        resp.headers["Content-Type"] = "application/wasm"
    elif name.endswith(".js"):
        resp.headers["Content-Type"] = "application/javascript"
    elif name.endswith(".data"):
        resp.headers["Content-Type"] = "application/octet-stream"
    return resp


@app.route("/")
def index():
    # Opening the Railway URL now launches the experiment.
    return send_from_directory(BUILD_DIR, "index.html")


@app.route("/<path:filename>")
def build_files(filename):
    # Serves Build/*.js, Build/*.wasm, Build/*.data, TemplateData/*, etc.
    # The specific API routes below (/health, /data, /export) are static
    # strings, so Flask matches them BEFORE this catch-all - no conflict.
    resp = send_from_directory(BUILD_DIR, filename)
    return _add_unity_headers(resp, filename)


# ---- API -----------------------------------------------------------------

@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/data", methods=["POST"])
def receive_data():
    """
    Accepts one trial object {...} or a batch [{...}, ...]. The whole object
    is stored as JSONB, so you can add new measures in Unity later without
    changing this schema.
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
                    session_id = str(row.get("session_id", "unknown"))
                    cur.execute(
                        "INSERT INTO trials (session_id, data) VALUES (%s, %s);",
                        (session_id, Jsonb(row)),
                    )
            conn.commit()
    except Exception as e:
        app.logger.error(f"DB insert failed: {e}")
        return jsonify({"error": "database error"}), 500

    return jsonify({"status": "saved", "rows": len(rows)}), 200


@app.route("/export", methods=["GET"])
def export_csv():
    """
    Returns ALL collected data as a single analysis-ready CSV.
    Protected by API_KEY: call /export?token=YOUR_KEY.
    """
    if API_KEY and request.args.get("token") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, session_id, received_at, data "
                "FROM trials ORDER BY id;"
            )
            rows = cur.fetchall()

    # Fixed columns first, then every key seen across all JSONB payloads
    # (preserving first-seen order). session_id is already a fixed column.
    data_keys, seen = [], {"session_id"}
    for _id, _sid, _ts, data in rows:
        for k in data:
            if k not in seen:
                seen.add(k)
                data_keys.append(k)

    fieldnames = ["id", "session_id", "received_at"] + data_keys

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for _id, sid, ts, data in rows:
        record = {"id": _id, "session_id": sid, "received_at": ts.isoformat()}
        record.update(data)
        writer.writerow(record)

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trials_export.csv"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))