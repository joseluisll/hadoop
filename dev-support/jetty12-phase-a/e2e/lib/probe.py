#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Record one end-to-end observation as a JSON line.

  probe.py http   --obs F --id ID --component C --url U [options]
  probe.py cli    --obs F --id ID --component C --rc N [--expect-rc N]
                  [--stdout-file F] [--shape sha256|text|lines|none]
                  [--expect-regex R]
  probe.py assert --obs F --id ID --component C --ok true|false [--detail D]

Every observation has "ok" (did this side meet the expectation) and "obs"
(a normalized view that must be identical on baseline and candidate). The
normalized view leaves out what legitimately changes from run to run:
timestamps, application/job/container ids, counts of running things, build
revision strings.

HTTPS: PROBE_CA names the CA certificate to trust. Kerberos: with
PROBE_SPNEGO=true requests go through curl --negotiate (ticket cache in
KRB5CCNAME); --no-auth sends one without credentials.

Exits 1 when the expectation is not met, so scenarios can stop early on a
failed prerequisite if they want to.
"""

import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from html.parser import HTMLParser

# Response headers whose values must match between the two sides. Every other
# header is compared by name only.
VALUE_HEADERS = {
    "content-type", "x-frame-options", "x-content-type-options",
    "x-xss-protection", "cache-control", "pragma", "strict-transport-security",
    "content-security-policy", "access-control-allow-origin",
    "access-control-allow-methods", "access-control-allow-headers",
    "www-authenticate", "allow", "content-encoding", "transfer-encoding",
    "vary", "server", "accept-ranges",
}
# Headers whose very presence depends on timing or body size.
IGNORED_HEADERS = {"date", "content-length", "expires", "last-modified", "etag",
                   "connection", "keep-alive"}

MASKS = [
    (re.compile(r"application_\d+_\d+"), "application_ID"),
    (re.compile(r"appattempt_\d+_\d+_\d+"), "appattempt_ID"),
    (re.compile(r"container_(e\d+_)?\d+_\d+_\d+_\d+"), "container_ID"),
    (re.compile(r"job_\d+_\d+"), "job_ID"),
    (re.compile(r"task_\d+_\d+_[mr]_\d+"), "task_ID"),
    (re.compile(r"attempt_\d+_\d+_[mr]_\d+_\d+"), "attempt_ID"),
    (re.compile(r"blk_-?\d+(_\d+)?"), "blk_ID"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "UUID"),
    (re.compile(r"\b\d{10,}\b"), "N"),
    (re.compile(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d([.,]\d+)?"), "DATETIME"),
    # java.util.Date#toString, e.g. "Tue Oct 13 15:00:02 UTC 2026" (fsck)
    (re.compile(r"\b[A-Z][a-z]{2} [A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d [A-Z]{2,5} \d{4}\b"),
     "DATETIME"),
    # Object#toString identity hashes, e.g. "...KMSClientProvider@76a2ddf3"
    (re.compile(r"(?<=[\w$])@[0-9a-f]{4,8}\b"), "@HASH"),
    # Delegation tokens (WebHDFS, HttpFS, KMS GETDELEGATIONTOKEN)
    (re.compile(r'"urlString":"[A-Za-z0-9_-]+"'), '"urlString":"TOKEN"'),
    # Durations in milliseconds, e.g. the namenode startup progress
    (re.compile(r'"elapsedTime":\d+'), '"elapsedTime":N'),
    # Each side runs its cluster under WORKDIR/<side>/, which shows in
    # configuration resource names and file paths.
    (re.compile(r"(?<=/)(baseline|candidate)(?=/)"), "SIDE"),
]


def mask(text):
    for regex, repl in MASKS:
        text = regex.sub(repl, text)
    return text


def json_shape(value):
    """Keys and value types, recursively; lists collapse to one merged element."""
    if isinstance(value, dict):
        return {k: json_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        merged = None
        kinds = set()
        for item in value:
            s = json_shape(item)
            if isinstance(s, dict):
                merged = merge_shapes(merged, s) if isinstance(merged, dict) else s
            else:
                kinds.add(json.dumps(s, sort_keys=True))
        out = []
        if merged is not None:
            out.append(merged)
        out.extend(json.loads(k) for k in sorted(kinds))
        return out
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "num"
    return "str"


def merge_shapes(a, b):
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge_shapes(out[k], v)
        else:
            out.setdefault(k, v)
    return out


def xml_shape(text):
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return {"xml_error": str(e).split(":")[0]}

    def walk(el):
        children = {}
        for c in el:
            tag = c.tag.split("}")[-1]
            children[tag] = merge_shapes(children.get(tag, {}), walk(c)) \
                if tag in children else walk(c)
        return {k: children[k] for k in sorted(children)}

    return {root.tag.split("}")[-1]: walk(root)}


class HtmlSummary(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self.assets = set()
        self.tags = set()

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "script" and a.get("src"):
            self.assets.add(a["src"])
        if tag == "link" and a.get("href") and "stylesheet" in (a.get("rel") or ""):
            self.assets.add(a["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def body_shape(kind, body, content_type):
    text = body.decode("utf-8", errors="replace")
    if kind == "none":
        return None
    if kind == "auto":
        if "json" in content_type:
            kind = "json"
        elif "html" in content_type:
            kind = "html"
        elif "xml" in content_type:
            kind = "xml"
        else:
            kind = "text"
    if kind == "json":
        try:
            return {"json": json_shape(json.loads(text))}
        except ValueError:
            return {"json_error": True, "first_line": mask(text.strip().split("\n")[0])[:200]}
    if kind == "xml":
        return {"xml": xml_shape(text)}
    if kind == "html":
        p = HtmlSummary()
        try:
            p.feed(text)
        except Exception:  # malformed HTML still gets a status/header record
            pass
        return {"html": {"title": mask(" ".join(p.title.split())),
                         "assets": sorted(mask(a) for a in p.assets),
                         "has_body": "body" in p.tags}}
    if kind == "sha256":
        return {"sha256": hashlib.sha256(body).hexdigest()}
    if kind == "lines":
        return {"lines": [mask(line) for line in text.splitlines()]}
    return {"first_line": mask(text.strip().split("\n")[0])[:200] if text.strip() else ""}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_urllib(a, data):
    req = urllib.request.Request(a.url, data=data, method=a.method)
    for h in a.header or []:
        k, _, v = h.partition(":")
        req.add_header(k.strip(), v.strip())
    handlers = [urllib.request.ProxyHandler({})]
    if os.environ.get("PROBE_CA"):
        ctx = ssl.create_default_context(cafile=os.environ["PROBE_CA"])
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    if not a.follow:
        handlers.append(NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    status, headers, body, error = None, {}, b"", None
    try:
        with opener.open(req, timeout=a.timeout) as resp:
            status, headers, body = resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        status, headers = e.code, dict(e.headers.items())
        try:
            body = e.read()
        except Exception:
            body = b""
    except Exception as e:  # connection refused, timeout, ...
        error = type(e).__name__ + ": " + str(e)[:200]
    return status, headers, body, error


def fetch_curl(a, data):
    """SPNEGO (Kerberos) needs a GSS-API client: curl --negotiate, with the
    ticket cache in KRB5CCNAME."""
    with tempfile.TemporaryDirectory() as tmp:
        hdr, out, inp = (os.path.join(tmp, n) for n in ("h", "b", "d"))
        cmd = ["curl", "-s", "-S", "--noproxy", "*", "--max-time", str(int(a.timeout)),
               "--negotiate", "-u", ":", "-D", hdr, "-o", out, "-w", "%{http_code}"]
        if os.environ.get("PROBE_CA"):
            cmd += ["--cacert", os.environ["PROBE_CA"]]
        if a.head_only or a.method == "HEAD":
            cmd += ["-I"]
        else:
            cmd += ["-X", a.method]
        if a.follow:
            cmd += ["-L"]
        for h in a.header or []:
            cmd += ["-H", h]
        if data is not None:
            with open(inp, "wb") as f:
                f.write(data)
            cmd += ["--data-binary", "@" + inp]
        cmd.append(a.url)
        p = subprocess.run(cmd, capture_output=True, timeout=a.timeout + 10)
        code = p.stdout.decode().strip()
        if not code.isdigit() or code == "000":
            return None, {}, b"", "curl: " + p.stderr.decode(errors="replace").strip()[:200]
        headers = {}
        if os.path.exists(hdr):
            # The last block is the final response (after 401 challenges,
            # 100-continue and followed redirects). newline="" keeps the
            # CRLFs that text mode would turn into plain newlines.
            with open(hdr, encoding="latin-1", newline="") as f:
                blocks = [b for b in f.read().split("\r\n\r\n") if b.strip()]
            for line in (blocks[-1].split("\r\n")[1:] if blocks else []):
                k, _, v = line.partition(":")
                headers[k.strip()] = v.strip()
        body = open(out, "rb").read() if os.path.exists(out) else b""
        return int(code), headers, body, None


def do_http(a):
    data = None
    if a.data is not None:
        data = a.data.encode()
    elif a.data_file:
        with open(a.data_file, "rb") as f:
            data = f.read()
    if os.environ.get("PROBE_SPNEGO") == "true" and not a.no_auth:
        status, headers, body, error = fetch_curl(a, data)
    else:
        status, headers, body, error = fetch_urllib(a, data)

    if a.out and body:
        with open(a.out, "wb") as f:
            f.write(body)

    lower = {k.lower(): v for k, v in headers.items()}
    content_type = " ".join(lower.get("content-type", "").lower().split())
    obs = {
        "method": a.method,
        "status": status,
        "error": error and re.sub(r"\[Errno \d+\] ", "", error.split(":")[0]),
        "headers": {k: (" ".join(v.split()) if k in VALUE_HEADERS else True)
                    for k, v in sorted(lower.items()) if k not in IGNORED_HEADERS
                    and k not in (a.ignore_header or [])},
    }
    if "set-cookie" in lower:
        # The cookie's name and attributes (HttpOnly, Secure, Path, ...)
        # matter; its value is random.
        name, _, rest = lower["set-cookie"].partition("=")
        attrs = sorted(p.strip().split("=")[0].lower() for p in rest.split(";")[1:] if p.strip())
        obs["headers"]["set-cookie"] = "; ".join([name.strip()] + attrs)
    if "location" in lower:
        loc = re.sub(r"^https?://[^/]+", "", lower["location"])
        obs["headers"]["location"] = mask(re.sub(r"[?&](delegation|offset|"
                                                 r"namenoderpcaddress)=[^&]*", "", loc))
    if status is not None and not a.head_only:
        obs["body"] = body_shape(a.shape, body, content_type)

    problems = []
    if error and not a.allow_error:
        problems.append(error)
    # "any": record whatever the server answers; the baseline/candidate
    # comparison is the check.
    expected = None if a.expect_status in ("", "any") else \
        [int(s) for s in a.expect_status.split(",")]
    if expected and status not in expected:
        problems.append(f"status {status}, expected {a.expect_status}")
    text = body.decode("utf-8", errors="replace")
    for r in a.expect_regex or []:
        if not re.search(r, text):
            problems.append(f"body does not match /{r}/")
    for r in a.reject_regex or []:
        if re.search(r, text):
            problems.append(f"body matches forbidden /{r}/")
    for pair in a.expect_json or []:
        path, _, want = pair.partition("=")
        got = json_get(text, path)
        if str(got) != want:
            problems.append(f"json {path} = {got!r}, expected {want!r}")
    if a.print_body:
        sys.stdout.write(text)
    return obs, problems, {"url": a.url, "expect_status": a.expect_status}


def json_get(text, path):
    try:
        v = json.loads(text)
        for part in path.split("."):
            v = v[int(part)] if isinstance(v, list) else v[part]
        return v
    except Exception:
        return None


def do_tls(a):
    """TLS as negotiated by a web server: protocol, cipher, certificate
    names, and whether protocols older than TLS 1.2 are refused."""
    from urllib.parse import urlparse
    u = urlparse(a.url)
    host, port = u.hostname, u.port or 443
    problems, obs = [], {}
    ctx = ssl.create_default_context(cafile=os.environ.get("PROBE_CA"))
    try:
        import socket
        with socket.create_connection((host, port), timeout=a.timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                cert = s.getpeercert()
                obs["protocol"] = s.version()
                obs["cipher"] = s.cipher()[0]
                obs["subject"] = dict(x[0] for x in cert.get("subject", ()))
                obs["san"] = sorted(v for _, v in cert.get("subjectAltName", ()))
    except Exception as e:
        problems.append(f"handshake failed: {type(e).__name__}: {e}"[:200])
    old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    old.check_hostname, old.verify_mode = False, ssl.CERT_NONE
    try:
        old.minimum_version = ssl.TLSVersion.TLSv1
        old.maximum_version = ssl.TLSVersion.TLSv1_1
        old.set_ciphers("ALL:@SECLEVEL=0")
        import socket
        with socket.create_connection((host, port), timeout=a.timeout) as raw:
            with old.wrap_socket(raw, server_hostname=host):
                obs["tls1.1_accepted"] = True
    except (ssl.SSLError, OSError, ValueError):
        obs["tls1.1_accepted"] = False
    if obs.get("tls1.1_accepted"):
        problems.append("server accepts TLS 1.1 or older")
    return obs, problems, {"url": a.url}


def do_cli(a):
    problems = []
    expect_rc = [int(x) for x in a.expect_rc.split(",")]
    if a.rc not in expect_rc:
        problems.append(f"exit code {a.rc}, expected {a.expect_rc}")
    obs = {"rc": a.rc}
    if a.stdout_file:
        with open(a.stdout_file, "rb") as f:
            out = f.read()
        if a.shape != "none":
            obs["output"] = body_shape(a.shape, out, "")
        text = out.decode("utf-8", errors="replace")
        for r in a.expect_regex or []:
            m = re.search(r, text)
            if not m:
                problems.append(f"output does not match /{r}/")
            elif m.groups():
                # Captured groups are part of the observation: they must match
                # between the two sides (e.g. a computed checksum).
                obs.setdefault("captured", []).extend(mask(g or "") for g in m.groups())
    return obs, problems, {"expect_rc": a.expect_rc}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("http", "cli", "assert", "tls"):
        p = sub.add_parser(name)
        p.add_argument("--obs", required=True)
        p.add_argument("--id", required=True)
        p.add_argument("--component", required=True)
        p.add_argument("--note", default="")
    h = sub.choices["http"]
    h.add_argument("--url", required=True)
    h.add_argument("--method", default="GET")
    h.add_argument("--data")
    h.add_argument("--data-file")
    h.add_argument("--header", action="append")
    h.add_argument("--expect-status", default="200")
    h.add_argument("--expect-regex", action="append")
    h.add_argument("--reject-regex", action="append")
    h.add_argument("--expect-json", action="append")
    h.add_argument("--shape", default="auto",
                   choices=["auto", "json", "xml", "html", "text", "sha256", "lines", "none"])
    h.add_argument("--ignore-header", action="append")
    h.add_argument("--follow", action="store_true")
    h.add_argument("--allow-error", action="store_true",
                   help="a connection error is the expected outcome; record it")
    h.add_argument("--no-auth", action="store_true",
                   help="never authenticate, even when PROBE_SPNEGO is set")
    h.add_argument("--head-only", action="store_true")
    h.add_argument("--out")
    h.add_argument("--print-body", action="store_true")
    h.add_argument("--timeout", type=float, default=60)
    c = sub.choices["cli"]
    c.add_argument("--rc", type=int, required=True)
    c.add_argument("--expect-rc", default="0")
    c.add_argument("--stdout-file")
    c.add_argument("--shape", default="none", choices=["none", "sha256", "text", "lines"])
    c.add_argument("--expect-regex", action="append")
    t = sub.choices["tls"]
    t.add_argument("--url", required=True)
    t.add_argument("--timeout", type=float, default=30)
    s = sub.choices["assert"]
    s.add_argument("--ok", required=True, choices=["true", "false"])
    s.add_argument("--detail", default="")
    a = ap.parse_args()

    if a.cmd == "http":
        obs, problems, expect = do_http(a)
    elif a.cmd == "cli":
        obs, problems, expect = do_cli(a)
    elif a.cmd == "tls":
        obs, problems, expect = do_tls(a)
    else:
        obs, problems, expect = {"ok": a.ok}, ([] if a.ok == "true" else [a.detail]), {}

    rec = {"id": a.id, "component": a.component, "type": a.cmd, "ok": not problems,
           "problems": problems, "expect": expect, "obs": obs, "note": a.note}
    with open(a.obs, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    status = "PASS" if not problems else "FAIL"
    print(f"  [{status}] {a.component} {a.id}" + (f": {'; '.join(problems)}" if problems else ""),
          file=sys.stderr)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
