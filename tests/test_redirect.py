import tempfile
import unittest
from pathlib import Path

from lmn import redirect


class RedirectTest(unittest.TestCase):
    def test_pages_lead_to_the_same_page_on_the_new_address(self):
        with tempfile.TemporaryDirectory() as d:
            site = Path(d)
            (site / "r").mkdir()
            (site / "index.html").write_text("<h1>old</h1>")
            (site / "r" / "abc.html").write_text("<h1>old</h1>")
            (site / "sw.js").write_text("// app cache")
            (site / "rt").mkdir()
            (site / "rt" / "abc.json").write_text("{}")
            redirect.run(site, "https://laziest-music-nerd.pages.dev")
            self.assertIn('url=https://laziest-music-nerd.pages.dev/r/abc.html"', (site / "r" / "abc.html").read_text())
            self.assertIn('location.replace("https://laziest-music-nerd.pages.dev/"', (site / "index.html").read_text())
            self.assertEqual((site / "rt" / "abc.json").read_text(), "{}")  # data files stay for the bot
            self.assertIn("unregister()", (site / "sw.js").read_text())  # the old app cache goes away


if __name__ == "__main__":
    unittest.main()
