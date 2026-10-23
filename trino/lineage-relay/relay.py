"""Relay OpenLineage events from Trino to DataHub with a stable job name per output table.

Trino names every job after its query id, so DataHub grows one DataFlow + DataJob
per query. DataHub splits a job name at the first dot into flow.job, so renaming
the job to `trino.<output table>` gives one flow and one job per target table
(re-runs overwrite that job instead of adding new ones).
"""
import json
import logging
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET_URL = os.environ["DATAHUB_OPENLINEAGE_URL"]
FLOW_NAME = os.getenv("FLOW_NAME", "trino")
PORT = int(os.getenv("PORT", "8000"))
FORWARD_TIMEOUT_SECONDS = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lineage-relay")


def rename_job(event):
    """Return a copy of the event with the job named after its first output table, or None if it has no output."""
    outputs = event.get("outputs") or []
    if not outputs:
        return None
    table = sorted(output["name"] for output in outputs)[0]
    job = {**event["job"], "name": f"{FLOW_NAME}.{table}"}
    return {**event, "job": job}


def forward(event):
    request = urllib.request.Request(
        TARGET_URL,
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT_SECONDS) as response:
        return response.status


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            renamed = rename_job(json.loads(body))
            status = 200 if renamed is None else forward(renamed)
        except (json.JSONDecodeError, KeyError) as error:
            log.warning("bad event: %s", error)
            status = 400
        except (urllib.error.URLError, TimeoutError) as error:
            log.error("DataHub unreachable: %s", error)
            status = 502
        self.send_response(status)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
