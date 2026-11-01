import unittest

from lmn import dossier, site


class DossierTest(unittest.TestCase):
    def test_members_from_english_infobox(self):
        text = ("{{Infobox musical artist\n| name = Radiohead\n| current_members = {{flatlist|\n* [[Thom Yorke]]\n* [[Jonny Greenwood]]\n"
                "* [[Colin Greenwood]]\n}}\n| past_members = \n}}\nRadiohead are...")
        self.assertEqual(dossier.members(text), (["Thom Yorke", "Jonny Greenwood", "Colin Greenwood"], []))

    def test_members_from_russian_infobox(self):
        text = "{{Музыкальный коллектив\n|Название = Кино\n|Состав = [[Виктор Цой]]<br>[[Юрий Каспарян]]\n|Бывшие участники = [[Алексей Рыбин]]\n}}"
        self.assertEqual(dossier.members(text), (["Виктор Цой", "Юрий Каспарян"], ["Алексей Рыбин"]))

    def test_first_paragraph_is_cut_at_a_sentence(self):
        long = "A. " * 400
        self.assertTrue(dossier.first_paragraph(long).endswith("."))
        self.assertLessEqual(len(dossier.first_paragraph(long)), dossier.EXTRACT_MAX)
        self.assertEqual(dossier.first_paragraph("One.\nTwo."), "One.")

    def test_rows_on_the_release_page(self):
        d = {"title": "Radiohead", "url": "https://ru.wikipedia.org/wiki/Radiohead", "extract": "Британская <рок-группа>.",
             "members": ["Thom Yorke"], "past_members": []}
        rows = site.dossier_rows(d)
        self.assertEqual(rows[0], ("Об артисте", '<span class="dossier">Британская &lt;рок-группа&gt;.</span>'
                                                 ' <a class="muted" href="https://ru.wikipedia.org/wiki/Radiohead">Википедия</a>'))
        self.assertEqual(rows[1], ("Состав", '<span class="dossier">Thom Yorke</span>'))
        self.assertEqual(site.dossier_rows({"checked": "x"}), [])


if __name__ == "__main__":
    unittest.main()
