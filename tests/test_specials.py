import unittest

from lmn import specials


class ListKind(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(specials.list_kind("Top 50 Albums of 2017"), "топ-50 альбомов 2017 года")
        self.assertEqual(specials.list_kind("TOP 50 ALBUMS OF 2016"), "топ-50 альбомов 2016 года")
        self.assertEqual(specials.list_kind("50 Best Albums of 2020"), "топ-50 альбомов 2020 года")
        self.assertEqual(specials.list_kind("Top 15 EPs of 2019"), "топ-15 EP 2019 года")
        self.assertEqual(specials.list_kind("TOP 10 WORST ALBUMS OF 2016"), "10 худших альбомов 2016 года")
        self.assertEqual(specials.list_kind("15 Worst Albums of the 2010s"), "15 худших альбомов 2010-х")
        self.assertEqual(specials.list_kind("Top 200 Albums of the 2010s"), "топ-100 альбомов 2010-х")
        self.assertEqual(specials.list_kind("Best Albums of the 2020s So Far"), "лучшие альбомы 2020-х (промежуточный список)")
        for t in ("Top 50 Songs of 2022", "Best Albums of 2023 So Far", "Top 5 Rap Albums of 2025", "Radiohead: Worst To Best"):
            self.assertIsNone(specials.list_kind(t), t)


class ParseList(unittest.TestCase):
    def test_description(self):
        desc = ("MY 2017 AOTY LIST IS FINALLY HERE! The albums are listed below.\n\nAlex Cameron - Forced Witness\n"
                "https://youtu.be/x\n\nOneohtrix Point Never- Replica\n100 gecs - 10,000 gecs (sorry for saying 1000 in vid)\n"
                "Austen's list: http://x\nJeremy - Not An Album\n===\nSubscribe - now")
        self.assertEqual(specials.parse_list(desc), [("Alex Cameron", "Forced Witness"), ("Oneohtrix Point Never", "Replica"),
                                                     ("100 gecs", "10,000 gecs (sorry for saying 1000 in vid)")])

    def test_matching(self):
        idx = specials.archive_index([
            {"id": "a", "artist_name": "King Gizzard & The Lizard Wizard", "album": "Nonagon Infinity"},
            {"id": "b", "artist_name": "Kids See Ghosts", "album": "Kids See Ghosts"},
            {"id": "c", "artist_name": "100 gecs", "album": "10,000 gecs"},
            {"id": "g", "artist_name": "X", "album": "Y", "guest": True}])
        self.assertEqual(specials.find_review(idx, "King Gizzard and the Lizard Wizard", "Nonagon Infinity"), "a")
        self.assertEqual(specials.find_review(idx, "Kids See Ghosts", "Self-Titled"), "b")
        self.assertEqual(specials.find_review(idx, "100 gecs", "10,000 gecs (sorry for saying 1000 in vid)"), "c")
        self.assertIsNone(specials.find_review(idx, "X", "Y"))  # a guest review is not Fantano's


class Verify(unittest.TestCase):
    ORDER = ["The King of Limbs", "Pablo Honey", "Amnesiac", "The Bends", "Hail to the Thief", "A Moon Shaped Pool",
             "Kid A", "In Rainbows", "OK Computer"]

    def test_same_order_in_a_comment(self):
        joke = "1. You\n2. Can't\n3. Rank\n4. Them\n9. Pablo Honey"
        countdown = ("9. OK Computer\n8. In Rainbows \n7. Kid A\n6. A Moon Shaped Pool\n5. Hail to the Thief\n4. The Bends\n"
                     "3. Amnesiac \n2. Pablo Honey\n1. The King of Limbs")
        self.assertFalse(specials.verify(self.ORDER, [joke]))
        self.assertTrue(specials.verify(self.ORDER, [joke, countdown]))

    def test_other_order_or_alphabet_is_not_enough(self):
        alphabet = "1. Amnesiac\n2. A Moon-Shaped Pool\n3. The Bends\n4. Hail to the Thief\n5. In Rainbows\n6. Kid A\n7. OK Computer"
        self.assertFalse(specials.verify(self.ORDER, [alphabet]))


class Badges(unittest.TestCase):
    def test_places_only_when_verified(self):
        data = {"rankings": [
            {"video_id": "uu8", "artist": "Radiohead", "date": "2017-04-17", "verified": True,
             "items": [{"album": "OK Computer", "place": 1, "t": 984, "review": "okc"}, {"album": "Pablo Honey", "place": 2, "t": None, "review": None}]},
            {"video_id": "zz", "artist": "Weezer", "date": "2019-03-21", "verified": False, "items": [{"album": "Pinkerton", "place": 1, "review": "pk"}]}],
            "lists": [{"video_id": "yu", "label": "топ-50 альбомов 2017 года", "items": [{"artist": "A", "album": "B", "review": "okc"}]}]}
        b = specials.badges(data)
        self.assertEqual(b["okc"], [
            {"text": "№1 из 2 в «Radiohead: от худшего к лучшему» (2017)", "url": "https://youtu.be/uu8"},
            {"text": "топ-50 альбомов 2017 года", "url": "https://youtu.be/yu"}])
        self.assertNotIn("pk", b)


if __name__ == "__main__":
    unittest.main()
