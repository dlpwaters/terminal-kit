import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
import zipfile

from terminalkit.download import DownloadError, download, safe_extract, validate_script


class Response(io.BytesIO):
    def __init__(self, data, headers):
        super().__init__(data)
        self.headers = headers


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, data, headers, sha):
        with patch("urllib.request.OpenerDirector.open", return_value=Response(data, headers)):
            return download("https://example.invalid/file", self.root / "artifact", sha, max_bytes=100)

    def test_verified_cached_download(self):
        data = b"complete file"
        digest = hashlib.sha256(data).hexdigest()
        self.get(data, {"Content-Length": str(len(data))}, digest)
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network on cache hit")):
            self.assertEqual(download("https://example.invalid/file", self.root / "artifact", digest).read_bytes(), data)

    def test_bad_checksum_no_cache(self):
        with self.assertRaises(DownloadError):
            self.get(b"partial", {}, "0" * 64)
        self.assertFalse((self.root / "artifact").exists())
        self.assertFalse(list(self.root.glob(".download-*")))

    def test_empty_truncated_and_html(self):
        for data, headers in [(b"", {}), (b"short", {"Content-Length": "20"}), (b"<html>error</html>", {}), (b"error", {"Content-Type": "text/html"})]:
            with self.subTest(data=data):
                with self.assertRaises(DownloadError):
                    self.get(data, headers, None)
        self.assertFalse((self.root / "artifact").exists())

    def test_http_failure_no_execution(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=OSError("HTTP 404")):
            with self.assertRaises(DownloadError):
                download("https://example.invalid/missing", self.root / "artifact")

    def test_transient_http_retry_is_bounded_and_errors_do_not_disclose_url(self):
        url = "https://example.invalid/file?private=hidden-value"
        error = urllib.error.HTTPError(url, 503, "Unavailable", {}, None)
        data = b"verified data"
        with patch("urllib.request.OpenerDirector.open", side_effect=[error, Response(data, {})]) as transport, \
             patch("terminalkit.download.time.sleep"):
            download(url, self.root / "artifact", hashlib.sha256(data).hexdigest())
            self.assertEqual(transport.call_count, 2)
        for status, calls in ((503, 2), (404, 1)):
            with patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.HTTPError(url, status, "Failure", {}, None)) as transport, \
                 patch("terminalkit.download.time.sleep"):
                with self.assertRaises(DownloadError) as failure:
                    download(url, self.root / "missing")
                self.assertEqual(transport.call_count, calls)
                self.assertIn(f"HTTP {status}", str(failure.exception))
                self.assertNotIn("hidden-value", str(failure.exception))
                self.assertFalse((self.root / "missing").exists())

    def test_size_and_protocol_limits(self):
        with self.assertRaises(DownloadError):
            self.get(b"x" * 101, {}, None)
        with self.assertRaises(DownloadError):
            download("http://example.invalid/insecure", self.root / "artifact")

    def test_scripts_require_shebang_and_valid_syntax(self):
        script = self.root / "install.sh"
        for data in (b"", b"<html>error", b"#!/bin/bash\nif broken\n"):
            script.write_bytes(data)
            with self.assertRaises(DownloadError):
                validate_script(script)
        script.write_bytes(b"#!/bin/bash\nprintf 'valid\\n'\n")
        validate_script(script)

    def test_tar_traversal_and_links(self):
        for name, link in [("../outside", None), ("/absolute", None), ("tool/link", "../../outside")]:
            archive = self.root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                info = tarfile.TarInfo(name)
                if link:
                    info.type = tarfile.SYMTYPE
                    info.linkname = link
                    tf.addfile(info)
                else:
                    info.size = 1
                    tf.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(DownloadError):
                safe_extract(archive, self.root / "dest")

    def test_safe_internal_symlinks(self):
        archive = self.root / "good.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            regular = tarfile.TarInfo("bin/tool")
            regular.size = 2
            tf.addfile(regular, io.BytesIO(b"ok"))
            link = tarfile.TarInfo("bin/alias")
            link.type = tarfile.SYMTYPE
            link.linkname = "tool"
            tf.addfile(link)
        safe_extract(archive, self.root / "dest")
        self.assertEqual((self.root / "dest/bin/alias").read_bytes(), b"ok")

    def test_zip_traversal(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside", b"oops")
        with self.assertRaises(DownloadError):
            safe_extract(archive, self.root / "dest")


if __name__ == "__main__":
    unittest.main()
