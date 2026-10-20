"""Offline ingestion/security checks. No test opens a network connection."""
import hashlib
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from quarry.sources import (SafeFetcher, SourceError, UnsafeURLError, canonical_url,
                                error_category, in_domain_scope, load_local, parse_document)


PUBLIC_ADDRESS = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]


class TransportFixture(SafeFetcher):
    def __init__(self, responses, scope=None, **kwargs):
        super().__init__(scope or {"domains": ["example.org"]}, resolver=lambda *a, **kw: PUBLIC_ADDRESS, **kwargs)
        self.responses = responses
        self.requests = []

    def _request(self, url, addresses, deadline):
        self.requests.append(url)
        return self.responses[url]


class SourceTests(unittest.TestCase):
    def test_text_keeps_code_point_offsets_and_original_spelling(self):
        text = "# Café terms\n\nCafé ☕ and Straße use naïve expressions.\n研究者: 这是新词。\n"
        document = parse_document(text.encode(), "text/markdown", "fixture.md", {"language": "mul"})
        self.assertEqual(document["text"], text)
        self.assertEqual(document["raw_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(document["text_sha256"], document["raw_sha256"])
        self.assertEqual(document["offset_unit"], "unicode_code_point")
        for block in document["blocks"]:
            self.assertTrue(document["text"][block["start"]:block["end"]])
        start = document["text"].index("Straße")
        self.assertEqual(document["text"][start:start + len("Straße")], "Straße")
        self.assertEqual(document["blocks"][0]["kind"], "heading")
        self.assertIsNone(document["publication_date"])
        self.assertIsNotNone(document["publication_date_reason"])

    def test_html_structure_metadata_and_safe_links(self):
        html = ("<html lang='es'><head><title>Una nota</title>"
                "<meta property='article:published_time' content='2025-02-03'/></head>"
                "<body><h2 id='terms'>Expresiones</h2><p>Un <b>café</b> ☕.</p>"
                "<table><tr><td>ñandú</td><td>bird</td></tr></table>"
                "<div data-speaker='Ana'><p>¿Qué significa sobremesa?</p></div>"
                "<a href='/next#section'>Next</a><a href='https://u:pw@example.org/x'>Unsafe</a>"
                "<script>EXFILTRATE SECRET</script><style>private</style></body></html>")
        document = parse_document(html.encode(), "text/html; charset=utf-8", "https://example.org/start")
        self.assertNotIn("EXFILTRATE", document["text"])
        self.assertNotIn("private", document["text"])
        self.assertEqual(document["title"], "Una nota")
        self.assertEqual(document["language"], "es")
        self.assertEqual(document["publication_date"], "2025-02-03")
        self.assertIsNone(document["publication_date_reason"])
        self.assertEqual(document["links"], ["https://example.org/next"])
        rows = [b for b in document["blocks"] if b["kind"] == "table_row"]
        self.assertEqual(document["text"][rows[0]["start"]:rows[0]["end"]], "ñandú | bird")
        turns = [b for b in document["blocks"] if b["kind"] == "turn"]
        self.assertEqual(turns[0]["location"]["speaker"], "Ana")
        self.assertEqual(document["blocks"][1]["heading"], "Expresiones")

    def test_explicit_turn_locations_are_validated(self):
        document = parse_document(b"Alice: term\nBob: sense\n", "text/plain", "dialogue.txt",
                                  {"turns": [{"start": 0, "end": 11, "speaker": "Alice"}]})
        self.assertTrue(any(b["location"].get("speaker") == "Alice" for b in document["blocks"]))
        with self.assertRaisesRegex(SourceError, "invalid_turn_offsets"):
            parse_document(b"short", "text/plain", "t.txt", {"turns": [{"start": -1, "end": 5}]})

    def test_unknown_binary_and_unresolved_encoding_are_visible(self):
        with self.assertRaisesRegex(SourceError, "unsupported_media_type"):
            parse_document(b"binary", "application/zip", "f.zip")
        with self.assertRaisesRegex(SourceError, "text_encoding_unresolved"):
            parse_document(b"\xff", "text/plain", "f.txt")
        with self.assertRaisesRegex(SourceError, "binary_text_unsupported"):
            parse_document(b"hello\0world", "text/plain", "f.txt")

    def test_local_file_is_independent_of_sibling_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.md"
            path.write_text("# Terms\nA boundary expression.", encoding="utf-8")
            document = load_local(path)
            self.assertEqual(document["locator"], str(path.resolve()))
            self.assertEqual(document["domain"], "local")

    def test_pdf_page_locations_and_explicit_ocr_limit(self):
        fixture = Path(__file__).parent.parent / "src" / "quarry" / "fixtures" / "jargon.pdf"
        self.assertTrue(fixture.is_file(), "packaged two-page fixture must exist")
        document = load_local(fixture)
        self.assertEqual(document["parser_info"]["pages"], 2)
        self.assertFalse(document["parser_info"]["ocr_performed"])
        heteroplasmy = next(b for b in document["blocks"] if "Heteroplasmy" in document["text"][b["start"]:b["end"]])
        biomarker = next(b for b in document["blocks"] if "biomarker" in document["text"][b["start"]:b["end"]])
        self.assertEqual(heteroplasmy["page"], 1)
        self.assertEqual(biomarker["page"], 2)

    def test_malformed_pdf_failure_is_safe(self):
        with self.assertRaisesRegex(SourceError, "pdf_parse_failed"):
            parse_document(b"not a pdf", "application/pdf", "broken.pdf")

    def test_pdf_worker_timeout_and_resource_failure_are_visible(self):
        with patch("quarry.sources._run_pdf_worker", side_effect=subprocess.TimeoutExpired("worker", 30)):
            with self.assertRaisesRegex(SourceError, "pdf_parse_timeout"):
                parse_document(b"fixture", "application/pdf", "source.pdf")
        failed = subprocess.CompletedProcess(["worker"], -9, stdout=b"")
        with patch("quarry.sources._run_pdf_worker", return_value=failed):
            with self.assertRaisesRegex(SourceError, "pdf_resource_limit_exceeded"):
                parse_document(b"fixture", "application/pdf", "source.pdf")

    def test_pdf_worker_uses_clean_environment_and_never_echoes_unknown_errors(self):
        successful = subprocess.CompletedProcess(["worker"], 0, stdout=b'{"pages":["one","two"],"title":"Fixture"}')
        with patch("quarry.sources._run_pdf_worker", return_value=successful):
            document = parse_document(b"fixture", "application/pdf", "source.pdf")
            self.assertEqual(document["text"], "one\n\ntwo")
            self.assertEqual(document["title"], "Fixture")
        malicious = subprocess.CompletedProcess(["worker"], 0, stdout=b'{"error":"source SECRET header"}')
        with patch("quarry.sources._run_pdf_worker", return_value=malicious):
            with self.assertRaisesRegex(SourceError, "^pdf_worker_invalid_response$"):
                parse_document(b"fixture", "application/pdf", "source.pdf")

    def test_pdf_worker_launch_has_private_fds_and_no_inherited_credentials(self):
        from quarry.sources import _run_pdf_worker
        captured = {}
        class FinishedProcess:
            returncode = 0
            def __init__(self, command, **kwargs):
                captured.update(kwargs)
                captured["command"] = command
                self.asserted_input = kwargs["stdin"].read()
                captured["input"] = self.asserted_input
                kwargs["stdout"].write(b'{"pages":["one"],"title":null}')
            def poll(self):
                return 0
        with patch("quarry.sources.subprocess.Popen", side_effect=FinishedProcess):
            result = _run_pdf_worker(b"fixture")
        self.assertEqual(captured["env"], {"PATH": "/usr/bin:/bin"})
        self.assertEqual(captured["stderr"], subprocess.DEVNULL)
        self.assertEqual(captured["input"], b"fixture")
        self.assertIn("-I", captured["command"])
        self.assertEqual(result.stdout, b'{"pages":["one"],"title":null}')

    def test_credentials_protocols_and_domain_boundaries(self):
        for url in ["https://u:secret@example.org/x", "https://example.org/?%61pi_key=secret",
                    "https://example.org/?access_token=secret", "file:///etc/passwd",
                    "https://example.org:8080/", "https://example.org/\nheader"]:
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    canonical_url(url)
        self.assertTrue(in_domain_scope("https://sub.example.org/a", {"domains": ["*.example.org"]}))
        self.assertTrue(in_domain_scope("https://example.org/a", {"domains": ["*.example.org"]}))
        self.assertFalse(in_domain_scope("https://badexample.org/a", {"domains": ["*.example.org"]}))
        self.assertFalse(in_domain_scope("https://sub.example.org/a", {"domains": ["example.org"]}))
        self.assertEqual(canonical_url("https://例え.jp/词汇?q=café"),
                         "https://xn--r8jz45g.jp/%E8%AF%8D%E6%B1%87?q=caf%C3%A9")

    def test_unparseable_publication_date_is_null_with_reason(self):
        document = parse_document(b"term", "text/plain", "source.txt", {"publication_date": "not known"})
        self.assertIsNone(document["publication_date"])
        self.assertEqual(document["publication_date_reason"], "publication_date_unparseable")

    def test_private_or_mixed_dns_answers_are_rejected_before_transport(self):
        for ip in ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "0.0.0.0", "224.0.0.1"]:
            address = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))
            fetcher = SafeFetcher({"domains": ["example.org"]}, resolver=lambda *a, **k: PUBLIC_ADDRESS + [address])
            with self.subTest(ip=ip), self.assertRaisesRegex(UnsafeURLError, "nonpublic_address_forbidden"):
                fetcher.fetch("https://example.org/")

    def test_dns_timeout_is_bounded(self):
        def slow_resolver(*args, **kwargs):
            time.sleep(0.2)
            return PUBLIC_ADDRESS
        fetcher = SafeFetcher({"domains": ["example.org"]}, timeout=0.01, resolver=slow_resolver)
        started = time.monotonic()
        with self.assertRaisesRegex(SourceError, "fetch_timeout"):
            fetcher.fetch("https://example.org/")
        self.assertLess(time.monotonic() - started, 0.15)

    def test_redirects_are_revalidated_and_response_size_is_bounded(self):
        fetcher = TransportFixture({"https://example.org/": (302, {"location": "https://other.org/a"}, b"")})
        with self.assertRaisesRegex(UnsafeURLError, "domain_out_of_scope"):
            fetcher.fetch("https://example.org/")
        self.assertEqual(fetcher.requests, ["https://example.org/"])
        fetcher = TransportFixture({"https://example.org/": (200, {"content-type": "text/plain"}, b"abcdefgh")}, max_bytes=4)
        with self.assertRaisesRegex(SourceError, "source_too_large"):
            fetcher.fetch("https://example.org/")

    def test_successful_redirect_has_lineage(self):
        fetcher = TransportFixture({"https://example.org/": (301, {"location": "/page"}, b""),
                                    "https://example.org/page": (200, {"content-type": "text/plain"}, b"new sense")})
        document = fetcher.fetch("https://example.org/")
        self.assertEqual(document["locator"], "https://example.org/page")
        self.assertEqual(document["retrieval"]["requested_locator"], "https://example.org/")
        self.assertEqual(document["retrieval"]["redirects"], ["https://example.org/"])

    def test_error_category_cannot_echo_credential_bearing_adapter_errors(self):
        self.assertEqual(error_category(SourceError("https://example.org/?token=SECRET")), "source_processing_failed")
        self.assertEqual(error_category(SourceError("fetch_timeout")), "fetch_timeout")


if __name__ == "__main__":
    unittest.main()
