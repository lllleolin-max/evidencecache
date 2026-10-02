from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from evidencecache import Manifest, ManifestError, apply_event, loads
from evidencecache.cli import main
from evidencecache.fixtures import AS_OF, fixture
from evidencecache.model import timestamp


class IngressTests(unittest.TestCase):
    def test_noncanonical_offset_components_are_rejected(self):
        for offset in ("+00:60", "-00:60", "+24:00", "-00:00"):
            with self.subTest(offset=offset), self.assertRaises(ManifestError):
                timestamp("2026-01-02T00:00:00" + offset)
        self.assertEqual(timestamp("2026-01-02T00:00:00+00:00"), timestamp(AS_OF))

    def test_malformed_events_raise_domain_error(self):
        manifest = Manifest.from_dict(fixture())
        fingerprint = manifest.fingerprint
        for event in (dict(kind="revoke", source=[], version="v1", at=AS_OF),
                      dict(kind="revoke", source="g0000-status", version=[], at=AS_OF),
                      dict(kind="publish", source="g0000-status", version={}, rebind_from="v1"),
                      dict(kind="publish", source="g0000-status", version=None)):
            with self.subTest(event=event), self.assertRaises(ManifestError):
                apply_event(manifest, event)
            self.assertEqual(manifest.fingerprint, fingerprint)

    def test_duplicate_event_keys_fail_without_overwriting_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "m.json").write_text(json.dumps(fixture()), encoding="utf-8")
            (root / "event.json").write_text('{"kind":"revoke","kind":"publish"}', encoding="utf-8")
            output = root / "out.json"
            output.write_text("existing", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(["apply", str(root / "m.json"), str(root / "event.json"), "--output", str(output)])
            self.assertEqual(code, 2)
            self.assertIn("duplicate JSON key", json.loads(err.getvalue())["detail"])
            self.assertEqual(output.read_text(), "existing")

    def test_surrogate_strings_and_mixed_sdk_keys_rejected(self):
        d = fixture()
        d["answers"][0]["text"] = "\ud800"
        with self.assertRaises(ManifestError):
            loads(json.dumps(d))
        d = fixture()
        d["sources"][0]["versions"][0]["facts"][0]["value"] = "\ud800"
        with self.assertRaises(ManifestError):
            Manifest.from_dict(d)
        with self.assertRaises(ManifestError):
            Manifest.from_dict({1: None, "other": None})


if __name__ == "__main__":
    unittest.main()
