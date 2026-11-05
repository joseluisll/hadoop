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
  probe.py raw    --obs F --id ID --component C --url U --request R [options]
  probe.py cli    --obs F --id ID --component C --rc N [--expect-rc N]
                  [--stdout-file F] [--shape sha256|text|lines|none]
                  [--expect-regex R]
  probe.py assert --obs F --id ID --component C --ok true|false [--detail D]

raw sends the request bytes as given, for what a client library would refuse
or rewrite: an encoded or malformed path, a missing Host header. R takes the
Python escapes (\\r\\n, \\x00), and {host} stands for the URL's host and port.

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
import codecs
import hashlib
import html
import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlparse

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
# Parts of header values that differ on every response: the GSS-API token of
# a SPNEGO reply ("Negotiate <token>", mutual authentication). The bare
# "Negotiate" challenge of a 401 stays as it is.
HEADER_MASKS = [
    (re.compile(r"\b(Negotiate|Kerberos|NTLM) [A-Za-z0-9+/=_-]{8,}"), r"\1 TOKEN"),
]


def header_value(v):
    v = " ".join(v.split())
    for regex, repl in HEADER_MASKS:
        v = regex.sub(repl, v)
    return v


# Follows the body's size; transfer-encoding says how a body is framed.
IGNORED_HEADERS = {"content-length"}

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
    # The two sides may run on different hosts.
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"), "IP"),
    (re.compile(r"\b" + re.escape(socket.gethostname()) + r"\b"), "HOST"),
    # A stack frame's line number changes with any recompiled jar, and its
    # length moves where a long text is cut. compare_e2e.py drops them as well,
    # for results recorded before this mask.
    (re.compile(r"\(([\w$]+\.(?:java|kt|scala|groovy)):\d+\)"), r"(\1)"),
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


def json_values(value):
    """The JSON values as they are, with every string masked (R34), so a
    difference shows what each side answered (T39)."""
    if isinstance(value, dict):
        return {k: json_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_values(v) for v in value]
    return mask(value) if isinstance(value, str) else value


def merge_shapes(a, b):
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge_shapes(out[k], v)
        else:
            out.setdefault(k, v)
    return out


def xml_shape(text):
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


# The row Jetty's sendError page keeps the reason in, as ResponseDetail reads it.
ERROR_PAGE_MESSAGE = re.compile(r"<th>\s*MESSAGE:\s*</th>\s*<td>(.*?)</td>", re.I | re.S)
MAX_ERROR_TEXT = 300


def string_leaves(value, path=""):
    if isinstance(value, dict):
        return [x for k in sorted(value) for x in string_leaves(value[k], f"{path}/{k}")]
    if isinstance(value, list):
        return [x for i, v in enumerate(value) for x in string_leaves(v, f"{path}[{i}]")]
    return [f"{path}={value}"] if isinstance(value, str) else []


def plain_text(text):
    """One line of text, from a page's message row or else without its markup."""
    message = ERROR_PAGE_MESSAGE.search(text)
    if message and message.group(1).strip():
        text = message.group(1)
    text = re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", text)
    return " ".join(html.unescape(re.sub(r"(?s)<[^>]*>", " ", text)).split())


def error_text(body, content_type):
    """What a client can tell the user about a refusal. The body's shape does
    not show this: a message that goes missing or changes leaves the shape as
    it was."""
    text = body.decode("utf-8", errors="replace")
    try:
        if "json" in content_type:
            found = string_leaves(json.loads(text))
        elif "xml" in content_type:
            found = [f"{e.tag.split('}')[-1]}={e.text.strip()}"
                     for e in ET.fromstring(text).iter() if (e.text or "").strip()]
        else:
            found = [plain_text(text)] if text.strip() else []
    except (ValueError, ET.ParseError):  # not the type it says
        found = [plain_text(text)] if text.strip() else []
    return [mask(x)[:MAX_ERROR_TEXT] for x in found]


def location_form(location):
    """How the Location is written, which the path recorded next to it hides:
    java.net.URL, as WebHdfsFileSystem uses it, cannot parse a relative one."""
    scheme = re.match(r"([a-zA-Z][a-zA-Z0-9+.-]*)://", location)
    if scheme:
        return scheme.group(1).lower() + " absolute"
    return "network-path" if location.startswith("//") else \
        "absolute-path" if location.startswith("/") else "relative"


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
    if kind in ("json", "json-values"):
        try:
            value = json.loads(text)
        except ValueError:
            return {"json_error": True, "first_line": mask(text.strip().split("\n")[0])[:200]}
        return {"json": json_shape(value) if kind == "json" else json_values(value)}
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


def header_lists(pairs):
    """{lower-case name: [values]}: a header sent several times (Set-Cookie,
    WWW-Authenticate) keeps every value."""
    out = {}
    for k, v in pairs:
        out.setdefault(k.strip().lower(), []).append(v.strip())
    return out


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
    status, reason, headers, body, error = None, None, {}, b"", None
    try:
        with opener.open(req, timeout=a.timeout) as resp:
            status, reason = resp.status, resp.reason
            headers, body = header_lists(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        status, reason, headers = e.code, e.reason, header_lists(e.headers.items())
        try:
            body = e.read()
        except Exception:
            body = b""
    except Exception as e:  # connection refused, timeout, ...
        error = type(e).__name__ + ": " + str(e)[:200]
    return status, reason, headers, body, error


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
            return None, None, {}, b"", "curl: " + p.stderr.decode(errors="replace").strip()[:200]
        reason, headers = None, {}
        if os.path.exists(hdr):
            # The last block is the final response (after 401 challenges,
            # 100-continue and followed redirects). newline="" keeps the
            # CRLFs that text mode would turn into plain newlines.
            with open(hdr, encoding="latin-1", newline="") as f:
                blocks = [b for b in f.read().split("\r\n\r\n") if b.strip()]
            lines = blocks[-1].split("\r\n") if blocks else [""]
            reason = lines[0].partition(" ")[2].partition(" ")[2]
            headers = header_lists(line.partition(":")[::2] for line in lines[1:])
        body = open(out, "rb").read() if os.path.exists(out) else b""
        return int(code), reason, headers, body, None


def http_obs(a, method, status, reason, headers, body, error):
    """The normalized view of one response, for http and raw."""
    content_type = " ".join(headers.get("content-type", [""])[0].lower().split())
    obs = {
        "method": method,
        "status": status,
        "reason": reason and mask(reason),
        "error": error and re.sub(r"\[Errno \d+\] ", "", error.split(":")[0]),
        "headers": {k: (", ".join(sorted(header_value(v) for v in vs))
                        if k in VALUE_HEADERS else True)
                    for k, vs in sorted(headers.items()) if k not in IGNORED_HEADERS
                    and k not in (a.ignore_header or [])},
    }
    if "set-cookie" in headers:
        # The cookie's name and attributes (HttpOnly, Secure, Path, ...)
        # matter; its value is random. One entry per cookie.
        cookies = []
        for c in headers["set-cookie"]:
            name, _, rest = c.partition("=")
            attrs = sorted(p.strip().split("=")[0].lower() for p in rest.split(";")[1:] if p.strip())
            cookies.append("; ".join([name.strip()] + attrs))
        obs["headers"]["set-cookie"] = " | ".join(sorted(cookies))
    if "location" in headers:
        loc = re.sub(r"^https?://[^/]+", "", headers["location"][0])
        obs["headers"]["location"] = mask(re.sub(r"[?&](delegation|offset|"
                                                 r"namenoderpcaddress)=[^&]*", "", loc))
        obs["location_form"] = location_form(headers["location"][0])
    if status is not None and not a.head_only:
        obs["body"] = body_shape(a.shape, body, content_type)
        if status >= 400:
            obs["error_text"] = error_text(body, content_type)
    return obs


def status_problems(a, status):
    # "any": record whatever the server answers; the baseline/candidate
    # comparison is the check.
    expected = None if a.expect_status in ("", "any") else \
        [int(s) for s in a.expect_status.split(",")]
    return [f"status {status}, expected {a.expect_status}"] \
        if expected and status not in expected else []


def do_raw(a):
    """Send the request as given and read what comes back, which may be
    nothing, or not HTTP: a server may refuse a request by closing the
    connection."""
    u = urlparse(a.url)
    host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
    request = codecs.decode(a.request.replace("{host}", f"{host}:{port}"),
                            "unicode_escape").encode("latin-1")
    method = request.split(b" ", 1)[0].decode("latin-1")
    version, status, reason, headers, body, error, reply = None, None, None, {}, b"", None, None
    try:
        sock = socket.create_connection((host, port), timeout=a.timeout)
        if u.scheme == "https":
            ctx = ssl.create_default_context(cafile=os.environ.get("PROBE_CA"))
            sock = ctx.wrap_socket(sock, server_hostname=host)
        with sock:
            sock.sendall(request)
            resp = http.client.HTTPResponse(sock, method=method)
            resp.begin()
            version = f"HTTP/{resp.version // 10}.{resp.version % 10}"
            status, reason, headers = resp.status, resp.reason, header_lists(resp.getheaders())
            try:
                body = resp.read()
            except http.client.IncompleteRead as e:
                body, error = e.partial, "IncompleteRead"
            except ConnectionError:
                # A body that ends with the connection: whether a closing
                # server's last packet is a FIN or a reset depends on timing.
                pass
    except ConnectionResetError:  # http.client.RemoteDisconnected is one too
        error = "connection closed without a response"
    except http.client.BadStatusLine as e:
        error, reply = "not an HTTP response", mask(e.line.strip())[:200]
    except (OSError, http.client.HTTPException) as e:
        error = type(e).__name__
    obs = http_obs(a, method, status, reason, headers, body, error)
    obs["version"] = version
    if reply is not None:
        obs["reply"] = reply
    return obs, status_problems(a, status), {"url": a.url, "expect_status": a.expect_status}


def do_http(a):
    data = None
    if a.data is not None:
        data = a.data.encode()
    elif a.data_file:
        with open(a.data_file, "rb") as f:
            data = f.read()
    if os.environ.get("PROBE_SPNEGO") == "true" and not a.no_auth:
        status, reason, headers, body, error = fetch_curl(a, data)
    else:
        status, reason, headers, body, error = fetch_urllib(a, data)

    if a.out and body:
        with open(a.out, "wb") as f:
            f.write(body)

    obs = http_obs(a, a.method, status, reason, headers, body, error)

    problems = []
    if error and not a.allow_error:
        problems.append(error)
    problems += status_problems(a, status)
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
    u = urlparse(a.url)
    host, port = u.hostname, u.port or 443
    problems, obs = [], {}
    ctx = ssl.create_default_context(cafile=os.environ.get("PROBE_CA"))
    try:
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
    for name in ("http", "raw", "cli", "assert", "tls"):
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
                   choices=["auto", "json", "json-values", "xml", "html", "text",
                            "sha256", "lines", "none"])
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
    r = sub.choices["raw"]
    r.add_argument("--url", required=True)
    r.add_argument("--request", required=True)
    r.add_argument("--expect-status", default="any")
    r.add_argument("--shape", default="auto",
                   choices=["auto", "json", "json-values", "xml", "html", "text",
                            "sha256", "lines", "none"])
    r.add_argument("--ignore-header", action="append")
    r.add_argument("--head-only", action="store_true")
    r.add_argument("--timeout", type=float, default=30)
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
    elif a.cmd == "raw":
        obs, problems, expect = do_raw(a)
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
