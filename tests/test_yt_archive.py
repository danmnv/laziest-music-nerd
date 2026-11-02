import unittest

from lmn.yt_archive import parse_title, title_keys


class TitleTest(unittest.TestCase):
    def test_current_format(self):
        self.assertEqual(parse_title("The Haxan Cloak - Excavation ALBUM REVIEW"), ("The Haxan Cloak", "Excavation"))
        self.assertEqual(parse_title("Jay-Z - The Blueprint 3 ALBUM REVIEW"), ("Jay-Z", "The Blueprint 3"))

    def test_2010_2012_format(self):
        self.assertEqual(parse_title("Cormorant- Dwellings ALBUM REVIEW"), ("Cormorant", "Dwellings"))
        self.assertEqual(parse_title("The Morning Benders- Big Echo Review"), ("The Morning Benders", "Big Echo"))
        self.assertEqual(parse_title("Marilyn Manson- Born Villain ALBUM REVIEW"), ("Marilyn Manson", "Born Villain"))
        self.assertEqual(parse_title("Jay-Z- The Blueprint 3 Review"), ("Jay-Z", "The Blueprint 3"))

    def test_not_album_reviews(self):
        self.assertIsNone(parse_title('Danger Mouse & Daniele Luppi- "The Rose With the Broken Neck" TRACK REVIEW'))
        self.assertIsNone(parse_title("Y U NO REVIEW: August '12"))
        self.assertIsNone(parse_title("Weekly Track Roundup: 10/28"))

    def test_self_titled_also_tries_artist_name(self):
        self.assertEqual(title_keys("TNGHT- Self-Titled EP REVIEW"), [("TNGHT", "Self-Titled"), ("TNGHT", "TNGHT")])


if __name__ == "__main__":
    unittest.main()
