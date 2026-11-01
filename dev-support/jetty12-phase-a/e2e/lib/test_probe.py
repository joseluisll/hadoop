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

"""Check that probe.py records what the Jetty 12 port is known to change.

Usage: test_probe.py

Answers each request from a small local server, as Jetty 9.4 and as Jetty 12
are known to, and fails unless the two give different observations. No cluster
or third-party module is needed.
"""

import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py")
PAGE = ("<html><head><title>Error 403 Forbidden</title></head><body><table>"
        "<tr><th>URI:</th><td>/x</td></tr><tr><th>MESSAGE:</th><td>%s</td></tr>"
        "</table><p>Powered by Jetty</p></body></html>")


class Server(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def reply(self, status, reason, body=b"", content_type="text/plain", **headers):
        self.send_response(status, reason)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for k, v in headers.items():
            self.send_header(k.replace("_", "-"), v)
        self.end_headers()
        self.wfile.write(body)

    def raw_reply(self, reply):
        self.wfile.write(reply)
        self.close_connection = True

    def do_GET(self):
        side, _, case = self.path.lstrip("/").partition("/")
        new = side == "new"
        if case == "reason":
            self.reply(403, "Forbidden" if new else "Anonymous requests are disallowed")
        elif case == "redirect":
            self.reply(302, "Found", Location="/webhdfs/" if new
                       else f"http://{self.headers['Host']}/webhdfs/")
        elif case == "page":
            self.reply(403, "Forbidden", (PAGE % ("" if new else "Refused")).encode(), "text/html")
        elif case == "json":
            detail = {"RemoteException": {"exception": "AccessControlException",
                                          "message": "denied" if new else f"denied by {socket.gethostname()}"}}
            self.reply(403, "Forbidden", json.dumps(detail).encode(), "application/json")
        elif case == "xml":
            self.reply(403, "Forbidden", b"<e><message>denied</message></e>", "application/xml")
        elif case == "bad-xml":
            self.reply(403, "Forbidden", b"<e>denied", "application/xml")
        elif case == "empty-xml":
            self.reply(403, "Forbidden", b"", "application/xml")
        elif case == "entity":
            self.reply(403, "Forbidden", (PAGE % ("it&#39;s" if new else "it's")).encode(), "text/html")
        elif case == "stack":
            frame = "(HttpServlet.java:1687)" if new else "(HttpServlet.java:687)"
            self.reply(500, "Server Error", ("x" * 270 + frame + "y" * 40).encode())
        elif case == "host-reason":
            self.reply(403, f"Refused by {socket.gethostname()} at 10.1.2.3")
        elif case == "host-port-redirect":
            self.reply(302, "Found", Location="myhost:8042/node")
        elif case == "chunked":
            self.raw_reply(b"HTTP/1.1 400 Bad\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n"
                           b"Content-Type: text/plain\r\n\r\n5\r\nhello\r\n0\r\n\r\n")
        elif case == "short":
            self.raw_reply(b"HTTP/1.1 400 Bad\r\nContent-Length: 10\r\nContent-Type: text/plain\r\n\r\nhey")
        elif case == "garbage":
            self.raw_reply(b"not http at all\r\n")
        elif case == "close":
            self.raw_reply(b"")
        else:
            self.reply(404, "Not Found")

    def log_message(self, *args):
        pass


def resetting_server(reply, wait):
    """A URL whose one connection sends reply and then, after wait seconds, is
    reset: http.server only ever closes politely."""
    listener = socket.create_server(("127.0.0.1", 0))

    def serve():
        conn, _ = listener.accept()
        conn.recv(65536)
        conn.sendall(reply)
        time.sleep(wait)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{listener.getsockname()[1]}"


def probe(tmp, cmd, url, *args, env=None):
    obs = os.path.join(tmp, "obs.jsonl")
    open(obs, "w").close()
    subprocess.run([sys.executable, "-I", PROBE, cmd, "--obs", obs, "--id", "x", "--component", "c",
                    "--url", url, *args], stderr=subprocess.DEVNULL, env={**os.environ, **(env or {})})
    with open(obs, encoding="utf-8") as f:
        return json.loads(f.read())["obs"]


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with tempfile.TemporaryDirectory() as tmp:
        def both(case, *args):
            return [probe(tmp, "http", f"{base}/{side}/{case}", "--expect-status", "any", *args)
                    for side in ("old", "new")]

        old, new = both("reason")
        assert (old["reason"], new["reason"]) == ("Anonymous requests are disallowed", "Forbidden")
        old, new = both("redirect")
        assert old["headers"]["location"] == new["headers"]["location"] == "/webhdfs/"
        assert (old["location_form"], new["location_form"]) == ("http absolute", "absolute-path")
        # Recorded whatever the shape, and the title alone would not tell them apart.
        old, new = both("page", "--shape", "none")
        assert old["error_text"] == ["Refused"], old
        assert new["error_text"] != old["error_text"], new
        old, new = both("json")
        assert old["body"] == new["body"], "the shape cannot tell these apart"
        assert old["error_text"] != new["error_text"], (old, new)
        assert "denied by HOST" in old["error_text"][1], old
        old, _ = both("xml")
        assert old["error_text"] == ["message=denied"], old
        # Bodies the XML parser refuses are still recorded, not a crash.
        old, _ = both("bad-xml")
        assert old["error_text"] == ["denied"], old
        old, _ = both("empty-xml")
        assert old["error_text"] == [], old
        old, new = both("entity")
        assert old["error_text"] == new["error_text"] == ["it's"], (old, new)
        # The cut falls after the frame, whose line number must not move it.
        old, new = both("stack")
        assert old["error_text"] == new["error_text"], (old, new)
        old, _ = both("host-reason")
        assert old["reason"] == "Refused by HOST at IP", old
        old, _ = both("host-port-redirect")
        assert old["location_form"] == "relative", old
        if shutil.which("curl"):
            url = f"{base}/old/reason"
            got = probe(tmp, "http", url, "--expect-status", "any", env={"PROBE_SPNEGO": "true"})
            assert got["reason"] == "Anonymous requests are disallowed", got
        # send_response adds Date; Jetty 9.4 sends none on an error page.
        assert old["headers"]["date"] is True, old

        def raw(path, url=base):
            request = f"GET {path} HTTP/1.1\\r\\nHost: {{host}}\\r\\nConnection: close\\r\\n\\r\\n"
            return probe(tmp, "raw", url, "--request", request)

        got = raw("/old/reason")
        assert (got["status"], got["reason"], got["version"]) == \
            (403, "Anonymous requests are disallowed", "HTTP/1.1"), got
        got = raw("/old/chunked")
        assert got["error_text"] == ["hello"], got
        got = raw("/old/short")
        assert (got["status"], got["error"], got["error_text"]) == (400, "IncompleteRead", ["hey"]), got
        got = raw("/old/garbage")
        assert (got["status"], got["error"], got["reply"]) == \
            (None, "not an HTTP response", "not http at all"), got
        # A close and a reset are one outcome: which one comes is timing.
        assert raw("/old/close")["error"] == "connection closed without a response"
        got = raw("/", resetting_server(b"", 0))
        assert got["error"] == "connection closed without a response", got
        got = raw("/", resetting_server(b"HTTP/1.1 400 Bad\r\nContent-Type: text/plain\r\n\r\n", 0.3))
        assert (got["status"], got["error"]) == (400, None), got
        # Sent as they are: urllib refuses or rewrites these.
        assert raw("/%c0/%00")["status"] == 404
    server.shutdown()
    print("test_probe: ok")


if __name__ == "__main__":
    main()
