"""Publish queued lifecycle facts as component checks with monotonic updates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from ticker.server.tls import verified_https_context

from ticker.ops.incidents import atomic_json
from ticker.ops.reporting import RuntimeReport


class GitHub:
    def __init__(self, repository, token, *, api="https://api.github.com"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid GitHub repository")
        self.root = api.rstrip("/") + "/repos/" + repository
        self.token = token

    def request(self, method, path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        request = Request(self.root + path, data=payload, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": "Bearer " + self.token,
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json", "User-Agent": "SportsTickerRuntimeReporter",
        })
        try:
            with urlopen(request, timeout=15, context=verified_https_context()) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"GitHub reporting failed with HTTP {error.code}") from None


def identity(report):
    label = "Reporting verification" if report.scope == "verification" else f"Ticker Server / {report.component} runtime"
    external = f"ticker-runtime:{report.site}:{report.scope}:{report.component}:{report.release}"
    return label, external


def description(report):
    messages = {"startup_failed": "Startup check failed", "deployment_interrupted": "Deployment stopped before confirmation",
                "runtime_unready": "Runtime readiness failed", "crash_loop": "Process crash loop detected",
                "rollback_started": "Rollback started", "rolled_back": "Rollback completed", "recovered": "Recovery verified"}
    text = messages[report.category]
    if report.restored_release:
        text += ". Recovery version: " + report.restored_release[:12]
    if report.scope == "verification":
        text = "Reporting test. " + text + ". Production services remain unchanged"
    return text


def publish(api, report, *, run_url, evidence=False):
    label, external = identity(report)
    found = None
    for page in range(1, 101):
        query = urlencode({"check_name": label, "filter": "all", "per_page": 100, "page": page})
        rows = api.request("GET", f"/commits/{report.release}/check-runs?{query}")["check_runs"]
        matches = [row for row in rows if row.get("external_id") == external]
        if matches:
            found = max(matches, key=lambda row: row["id"])
            break
        if len(rows) < 100:
            break
    if found:
        previous = re.search(r"^Sequence: ([0-9]+)$", found.get("output", {}).get("summary", ""), re.M)
        if previous and int(previous[1]) >= report.sequence:
            return found["id"]
    text = description(report)
    summary = f"{text}.\n\nComponent: {report.component}\nRevision: {report.release}\nReport: {report.id}\nSequence: {report.sequence}"
    summary += "\n\nEncrypted diagnostic evidence is attached to the reporting workflow." if evidence else "\n\nDetailed evidence remains on the server."
    body = {"name": label, "external_id": external, "status": "completed", "conclusion": report.state,
            "details_url": run_url, "output": {"title": text, "summary": summary}}
    if found:
        value = api.request("PATCH", f"/check-runs/{found['id']}", body)
    else:
        value = api.request("POST", "/check-runs", {**body, "head_sha": report.release})
    if value.get("external_id") != external or value.get("conclusion") != report.state:
        raise ValueError("GitHub did not confirm the runtime report")
    return value["id"]


def deliver(api, envelope, *, run_url, acknowledgement, evidence=False):
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "busy", "reports"} or envelope["schema_version"] != 1:
        raise ValueError("runtime report envelope is invalid")
    if not isinstance(envelope["reports"], list) or len(envelope["reports"]) > 100 or type(envelope["busy"]) is not bool:
        raise ValueError("runtime report batch is invalid")
    reports = [RuntimeReport.parse(value) for value in envelope["reports"]]
    confirmed, failures = [], []
    for report in sorted(reports, key=lambda item: item.sequence):
        try:
            publish(api, report, run_url=run_url, evidence=evidence)
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            failures.append(type(error).__name__)
        else:
            confirmed.append(report.id)
            print(f"Confirmed {report.scope} {report.component} {report.state} for {report.release[:12]}")
        atomic_json(acknowledgement, {"schema_version": 1, "report_ids": confirmed})
    if failures:
        raise RuntimeError(f"GitHub left {len(failures)} runtime reports unconfirmed")
    return len(confirmed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ack-output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--evidence", action="store_true")
    args = parser.parse_args()
    url = urlsplit(args.run_url)
    if url.scheme != "https" or url.netloc != "github.com" or not url.path.startswith("/" + args.repository + "/actions/runs/"):
        raise ValueError("runtime report link must identify this repository workflow")
    if args.input.stat().st_size > 1_000_000:
        raise ValueError("runtime report batch is too large")
    api = GitHub(args.repository, os.environ["GH_TOKEN"])
    deliver(api, json.loads(args.input.read_text(encoding="utf-8")), run_url=args.run_url,
            acknowledgement=args.ack_output, evidence=args.evidence)


if __name__ == "__main__":
    main()
