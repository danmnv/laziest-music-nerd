"""Exact streaming editions verified for reviews that an album search can misidentify.

The IDs identify the corresponding album pages on Deezer and Apple Music.
The cover, year, duration and tracks came from that Deezer ID.
Zero means the review has no corresponding streaming edition.
"""

REVIEW_EDITIONS = {
    "6684c32c49ea2a054e092477": {  # Weezer (Teal Album)
        "apple": "https://music.apple.com/us/album/weezer-teal-album/1450270988",
        "album": {
            "dz": 85310172,
            "cv": "https://cdn-images.dzcdn.net/images/cover/3f24bc187290f1fed3eb8f1778c60fb3/1000x1000-000000-80-0-0.jpg",
            "y": "2019",
            "min": 36,
            "t": [
                ["Africa", 238],
                ["Everybody Wants to Rule the World", 244],
                ["Sweet Dreams (Are Made of This)", 214],
                ["Take on Me", 223],
                ["Happy Together", 145],
                ["Paranoid", 164],
                ["Mr. Blue Sky", 286],
                ["No Scrubs", 190],
                ["Billie Jean", 294],
                ["Stand by Me", 180],
            ],
        },
    },
    "6684c32c49ea2a054e0920a9": {  # Weezer (White Album)
        "apple": "https://music.apple.com/us/album/weezer-white-album/1100739016",
        "album": {
            "dz": 12737712,
            "cv": "https://cdn-images.dzcdn.net/images/cover/39381d55274f8fd48d6c07158c76ef25/1000x1000-000000-80-0-0.jpg",
            "y": "2016",
            "min": 34,
            "t": [
                ["California Kids", 205],
                ["Wind in Our Sail", 173],
                ["Thank God for Girls", 210],
                ["(Girl We Got A) Good Thing", 205],
                ["Do You Wanna Get High?", 207],
                ["King of the World", 204],
                ["Summer Elaine and Drunk Dori", 205],
                ["L.A. Girlz", 209],
                ["Jacked Up", 173],
                ["Endless Bummer", 254],
            ],
        },
    },
    "6684c32c49ea2a054e09248e": {  # Weezer (Black Album)
        "apple": "https://music.apple.com/us/album/weezer-black-album/1442329821",
        "album": {
            "dz": 88629512,
            "cv": "https://cdn-images.dzcdn.net/images/cover/14a8fadbc5bb5b1056c44bf5f661a259/1000x1000-000000-80-0-0.jpg",
            "y": "2019",
            "min": 38,
            "t": [
                ["Can't Knock the Hustle", 220],
                ["Zombie Bastards", 251],
                ["High as a Kite", 227],
                ["Living in L.A.", 217],
                ["Piece of Cake", 196],
                ["I’m Just Being Honest", 236],
                ["Too Many Thoughts in My Head", 241],
                ["The Prince Who Wanted Everything", 202],
                ["Byzantine", 247],
                ["California Snow", 214],
            ],
        },
    },
    "6a8d3ead93fb940337491c90": {  # Weezer (Gold Album)
        "apple": "https://music.apple.com/us/album/weezer/6772364953",
        "album": {
            "dz": 989348601,
            "cv": "https://cdn-images.dzcdn.net/images/cover/8da35ebf20c7f714b6ee30040c10a118/1000x1000-000000-80-0-0.jpg",
            "y": "2026",
            "min": 33,
            "t": [
                ["Say Yes", 184],
                ["Shine Again", 245],
                ["Don't Make It Weird", 169],
                ["We Might as Well Be Strangers (ft. Wednesday)", 214],
                ["C.E.O.", 174],
                ["Hoops", 155],
                ["Nowhere", 168],
                ["The Show Must Go On", 203],
                ["Up In the Clouds", 219],
                ["The LA Sound", 237],
            ],
        },
    },
    # The 2025 TND post quotes an April Fools' video about NAV; its headline is Bully.
    # The later EP and full album are both unrelated to that video's review.
    "67ec9e8ba176bb07ab370e71": {"apple": 0, "album": 0},
    "69cdd0bac4ab5e049cd37b65": {  # Ye — Bully (2026), the 18-track album
        "apple": "https://music.apple.com/us/album/bully/1888707282",
        "album": {
            "dz": 949407771,
            "cv": "https://cdn-images.dzcdn.net/images/cover/e6c8292811aac14c1c4d25d768b863ee/1000x1000-000000-80-0-0.jpg",
            "y": "2026",
            "min": 42,
            "t": [
                ["KING", 126],
                ["THIS A MUST", 86],
                ["FATHER (feat. Travis Scott)", 169],
                ["ALL THE LOVE (feat. Andre Troutman)", 229],
                ["PUNCH DRUNK", 108],
                ["WHATEVER WORKS", 117],
                ["MAMA’S FAVORITE (feat. Nine Vicious)", 154],
                ["SISTERS AND BROTHERS", 165],
                ["BULLY (feat. CeeLo Green)", 147],
                ["HIGHS AND LOWS", 111],
                ["I CAN’T WAIT", 127],
                ["WHITE LINES (feat. Andre Troutman)", 130],
                ["CIRCLES", 91],
                ["PREACHER MAN", 181],
                ["BEAUTY AND THE BEAST", 107],
                ["DAMN", 123],
                ["LAST BREATH (feat. Peso Pluma)", 186],
                ["THIS ONE HERE", 180],
            ],
        },
    },
}
