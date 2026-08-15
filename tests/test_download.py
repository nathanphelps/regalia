"""Downloading, against a server that misbehaves in the ways real ones do.

A local server rather than a mocked socket, because the two failures worth
covering are both about what arrives on the wire: a reply that claims more bytes
than it sends, and a 200 that is not JSON at all. Both come from the network
between the user and Nexus rather than from Nexus, which is why neither raises
on its own.
"""

from __future__ import annotations

import http.server
import socketserver
import threading

import pytest

from regalia.nexus import NexusError, NexusOffline
from regalia.nexus.client import NexusClient
from regalia.nexus.download import fetch, safe_name


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802 - the base class names it
        if self.path.startswith("/short"):
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.send_header("Content-Disposition", 'attachment; filename="mod.zip"')
            self.end_headers()
            self.wfile.write(b"x" * 200)
        elif self.path.startswith("/whole"):
            self.send_response(200)
            self.send_header("Content-Length", "200")
            self.send_header("Content-Disposition", 'attachment; filename="good.zip"')
            self.end_headers()
            self.wfile.write(b"x" * 200)
        elif self.path.startswith("/nolength"):
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="odd.zip"')
            self.end_headers()
            self.wfile.write(b"x" * 50)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Sign in to continue</body></html>")

    def do_POST(self):  # noqa: N802
        self.do_GET()


@pytest.fixture
def server():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_a_reply_shorter_than_it_claimed_is_refused(tmp_path, server):
    with pytest.raises(NexusOffline, match="stopped early"):
        fetch(f"{server}/short", tmp_path, "fallback.zip")


def test_nothing_is_left_behind_when_it_is_refused(tmp_path, server):
    with pytest.raises(NexusOffline):
        fetch(f"{server}/short", tmp_path, "fallback.zip")

    # Neither the scratch file nor a half archive the scanner would pick up.
    assert list(tmp_path.iterdir()) == []


def test_a_complete_reply_is_kept(tmp_path, server):
    path = fetch(f"{server}/whole", tmp_path, "fallback.zip")

    assert path.name == "good.zip"
    assert path.stat().st_size == 200


def test_a_reply_with_no_length_is_taken_at_its_word(tmp_path, server):
    # Nothing to compare against, so refusing it would reject every chunked
    # reply. The archive either extracts or it does not.
    path = fetch(f"{server}/nolength", tmp_path, "fallback.zip")

    assert path.stat().st_size == 50


def test_a_page_that_is_not_json_reports_as_a_nexus_error(
    tmp_path, server, monkeypatch
):
    # A hotel network or a proxy answers 200 with an HTML sign-in page. Letting
    # the decode failure escape would show a traceback, because every caller
    # guards against NexusError and a ValueError is not one.
    import regalia.nexus.client as client_module

    monkeypatch.setattr(client_module, "V1_BASE", server)
    client = NexusClient("dummy-key")

    with pytest.raises(NexusError, match="did not answer with JSON"):
        client.rest("/users/validate.json")


def test_a_server_supplied_name_cannot_escape_the_folder():
    # The name comes from a header, so it is the server's word rather than the
    # user's. Directories are dropped, and a leading dot goes with them: a
    # download that lands as a hidden file is one the user cannot find.
    assert safe_name("../../.bashrc", "fallback.7z") == "bashrc"
    assert safe_name("/etc/passwd", "fallback.7z") == "passwd"
    assert safe_name("...", "fallback.7z") == "fallback.7z"
    assert safe_name("", "fallback.7z") == "fallback.7z"


@pytest.mark.parametrize(
    "supplied",
    ["../../evil.zip", "/tmp/evil.zip", "a/b/evil.zip", "..\\..\\evil.zip"],
)
def test_no_supplied_name_carries_a_separator(supplied):
    cleaned = safe_name(supplied, "fallback.7z")

    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert not cleaned.startswith(".")
