import hashlib
import tempfile
import unittest
from pathlib import Path

from spory.updater import UpdateError, is_newer, parse_release, parse_version, verify_checksum


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_version("v1.2.10"), (1, 2, 10))
        self.assertEqual(parse_version("0.3.0rc1"), (0, 3, 0))

    def test_newer(self):
        self.assertTrue(is_newer("0.2.0", "0.1.9"))
        self.assertTrue(is_newer("v0.10.0", "0.9.0"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertFalse(is_newer("0.0.9", "0.1.0"))


class ReleaseTests(unittest.TestCase):
    def payload(self, **kw):
        data = {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/Error0229/spory/releases/tag/v0.2.0",
            "assets": [
                {"name": "spory-setup-0.2.0.exe", "browser_download_url": "https://x/setup.exe"},
                {"name": "spory-setup-0.2.0.exe.sha256", "browser_download_url": "https://x/setup.sha256"},
                {"name": "notes.txt", "browser_download_url": "https://x/notes"},
            ],
        }
        data.update(kw)
        return data

    def test_picks_installer_and_checksum(self):
        r = parse_release(self.payload())
        self.assertEqual(r.version, "0.2.0")
        self.assertEqual(r.installer_url, "https://x/setup.exe")
        self.assertEqual(r.checksum_url, "https://x/setup.sha256")

    def test_ignores_prereleases_and_missing_installer(self):
        self.assertIsNone(parse_release(self.payload(prerelease=True)))
        self.assertIsNone(parse_release(self.payload(assets=[])))


class ChecksumTests(unittest.TestCase):
    def test_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.exe"
            path.write_bytes(b"installer bytes")
            digest = hashlib.sha256(b"installer bytes").hexdigest()
            verify_checksum(path, f"{digest}  spory-setup-0.2.0.exe\n")
            with self.assertRaises(UpdateError):
                verify_checksum(path, "0" * 64)
            with self.assertRaises(UpdateError):
                verify_checksum(path, "")


if __name__ == "__main__":
    unittest.main()
