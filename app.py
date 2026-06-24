"""
AMIPI Product Data Extractor — Flask Web API
=============================================
Wraps extractor.py logic and serves the frontend UI.

Endpoints:
  GET  /                      → Serve the HTML frontend
  POST /api/extract/single    → Extract a single product description
  POST /api/extract/batch     → Process a CSV file (multipart/form-data, field: "file")
  GET  /api/results/download  → Download last batch result as JSON
  GET  /api/health            → Health check
"""

from dotenv import load_dotenv
load_dotenv()

import os
import io
import csv
import json
import time
import tempfile
from flask import Flask, request, jsonify, render_template, send_file, Response

# Import extractor logic directly
from extractor import process_row, run as run_extractor

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit

# In-memory store for the last batch results (for download)
_last_batch_results = []


def get_api_key() -> str | None:
    """Read API key from env (supports runtime override via X-API-Key header)."""
    return request.headers.get("X-API-Key") or os.environ.get("GEMINI_API_KEY")


# ──────────────────────────────────────────────
#  ROUTES
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    api_key = os.environ.get("GEMINI_API_KEY")
    return jsonify({
        "status": "ok",
        "gemini_api_key_set": bool(api_key),
    })


@app.route("/api/extract/single", methods=["POST"])
def extract_single():
    """
    Accepts JSON: { "text": "...", "api_key": "..." (optional) }
    Returns the extracted product record.
    """
    body = request.get_json(silent=True) or {}
    raw_text = (body.get("text") or "").strip()
    if not raw_text:
        return jsonify({"error": "Field 'text' is required and must not be empty."}), 400

    api_key = body.get("api_key") or get_api_key()
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not set. Provide it in the environment or pass 'api_key' in the request body."}), 400

    try:
        result = process_row(0, raw_text, api_key)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/extract/batch", methods=["POST"])
def extract_batch():
    """
    Accepts: multipart/form-data with field 'file' (CSV) and optional field 'api_key'.
    CSV must have columns: id, raw_product_text
    Returns JSON array of extracted records.
    """
    global _last_batch_results

    api_key = request.form.get("api_key") or get_api_key()
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY is not set. Provide it via env or the api_key form field."}), 400

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Send a CSV as multipart field 'file'."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Uploaded file has no filename."}), 400
    if not file.filename.lower().endswith(".csv"):
        return jsonify({"error": "Only CSV files are accepted."}), 400

    # Read CSV from memory
    content = file.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    if not rows:
        return jsonify({"error": "CSV is empty or missing headers."}), 400

    if "raw_product_text" not in reader.fieldnames:
        return jsonify({"error": "CSV must have a 'raw_product_text' column."}), 400

    results = []
    for row in rows:
        row_id = row.get("id", len(results) + 1)
        raw_text = (row.get("raw_product_text") or "").strip()
        if not raw_text:
            results.append({
                "id": row_id,
                "raw_product_text": "",
                "notes_or_warnings": ["Empty raw_product_text — skipped"],
                "confidence_score": 0.0,
            })
            continue
        try:
            result = process_row(int(row_id) if str(row_id).isdigit() else 0, raw_text, api_key)
            results.append(result)
        except Exception as e:
            results.append({
                "id": row_id,
                "raw_product_text": raw_text,
                "notes_or_warnings": [f"Processing error: {e}"],
                "confidence_score": 0.0,
            })
        # Respect Gemini Free Tier (~12 RPM)
        time.sleep(5)

    _last_batch_results = results
    return jsonify({"success": True, "count": len(results), "results": results})


@app.route("/api/results/download")
def download_results():
    """Download the last batch extraction results as JSON."""
    global _last_batch_results
    if not _last_batch_results:
        return jsonify({"error": "No batch results available yet. Run a batch extraction first."}), 404

    data = json.dumps(_last_batch_results, indent=2, ensure_ascii=False)
    buf = io.BytesIO(data.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/json",
        as_attachment=True,
        download_name="extracted_products.json",
    )


# ──────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"\n🚀  AMIPI Extractor UI  →  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
