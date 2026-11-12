"""Check README.html, the copy the integration serves, matches README.md.

If this fails, run:  python tools/build_ipixelcolorha_readme.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "ipixelcolorha"


class ReadmeHtmlTest(unittest.TestCase):
    def test_html_is_built_from_current_readme(self) -> None:
        text = (COMPONENT / "README.md").read_text(encoding="utf-8")
        digest = hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        page = (COMPONENT / "README.html").read_text(encoding="utf-8")
        match = re.search(r"<!-- source-sha256: ([0-9a-f]{64}) -->", page)
        self.assertIsNotNone(match, "README.html has no source digest")
        self.assertEqual(
            match.group(1),
            digest,
            "README.html is out of date: run python tools/build_ipixelcolorha_readme.py",
        )

    def test_manifest_and_served_page(self) -> None:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        const = (COMPONENT / "const.py").read_text(encoding="utf-8")
        served = re.search(r'^README_URL = "([^"]+)"', const, re.M).group(1)
        self.assertTrue(manifest["documentation"].startswith("https://github.com/"))
        self.assertTrue(served.endswith("/README.html"))
        self.assertIn("http", manifest["dependencies"])

    def test_section_links_resolve(self) -> None:
        page = (COMPONENT / "README.html").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([^"]+)"', page))
        for anchor in re.findall(r'href="#([^"]+)"', page):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, ids)


if __name__ == "__main__":
    unittest.main()
