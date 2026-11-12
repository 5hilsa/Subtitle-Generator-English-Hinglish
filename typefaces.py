#!/usr/bin/env python3
"""The caption font library. Every font here ships in ./fonts, so exports look the
same on Mac, Windows and the server, with no internet needed at export time.

All are from Google Fonts under the SIL Open Font License or Apache 2.0 (both
allow commercial use); each font's licence is in fonts/licenses/. Files are
static TTFs with Latin and, where the font has it, Devanagari.

  name   the font's full name inside the file (what libass matches on)
  scale  size correction so every font looks about as big as Poppins
  hindi  True if it can draw Devanagari (Hindi script)
"""

GROUPS = {"bold": "Bold & clean", "fun": "Fun & display", "hand": "Handwritten",
          "serif": "Serif & elegant", "hindi": "Made for Hindi"}

#  key: (label, name, file, group, scale, hindi)
FONTS = {
    'poppins': ('Poppins', 'Poppins SemiBold', 'Poppins-SemiBold.ttf', 'bold', 1.0, True),
    'poppins_xb': ('Poppins ExtraBold', 'Poppins ExtraBold', 'Poppins-ExtraBold.ttf', 'bold', 1.0, True),
    'montserrat': ('Montserrat', 'Montserrat Thin ExtraBold', 'Montserrat-800.ttf', 'bold', 1.01, False),
    'montserrat_black': ('Montserrat Black', 'Montserrat Thin Black', 'Montserrat-900.ttf', 'bold', 1.01, False),
    'montserrat_italic': ('Montserrat Black Italic', 'Montserrat Thin Black Italic', 'Montserrat-900italic.ttf', 'bold', 1.01, False),
    'inter': ('Inter', 'Inter ExtraBold', 'Inter-800.ttf', 'bold', 0.98, False),
    'inter_semibold': ('Inter SemiBold', 'Inter SemiBold', 'Inter-600.ttf', 'bold', 0.98, False),
    'anton': ('Anton', 'Anton Regular', 'Anton-400.ttf', 'bold', 0.8, False),
    'bebas': ('Bebas Neue', 'Bebas Neue Regular', 'BebasNeue-400.ttf', 'bold', 0.89, False),
    'oswald': ('Oswald', 'Oswald Bold', 'Oswald-700.ttf', 'bold', 0.9, False),
    'archivo_black': ('Archivo Black', 'Archivo Black Regular', 'ArchivoBlack-400.ttf', 'bold', 1.03, False),
    'league_spartan': ('League Spartan', 'League Spartan Thin ExtraBold', 'LeagueSpartan-800.ttf', 'bold', 1.17, False),
    'outfit': ('Outfit', 'Outfit Thin ExtraBold', 'Outfit-800.ttf', 'bold', 1.05, False),
    'figtree': ('Figtree', 'Figtree Light ExtraBold', 'Figtree-800.ttf', 'bold', 1.04, False),
    'jakarta': ('Plus Jakarta Sans', 'Plus Jakarta Sans ExtraBold', 'PlusJakartaSans-800.ttf', 'bold', 0.97, False),
    'manrope': ('Manrope', 'Manrope ExtraLight ExtraBold', 'Manrope-800.ttf', 'bold', 0.99, False),
    'rubik': ('Rubik', 'Rubik Light ExtraBold', 'Rubik-800.ttf', 'bold', 1.03, False),
    'raleway': ('Raleway', 'Raleway Thin ExtraBold', 'Raleway-800.ttf', 'bold', 1.01, False),
    'nunito': ('Nunito', 'Nunito ExtraLight Black', 'Nunito-900.ttf', 'bold', 1.02, False),
    'barlow_cond': ('Barlow Condensed', 'Barlow Condensed ExtraBold', 'BarlowCondensed-800.ttf', 'bold', 1.03, False),
    'space_grotesk': ('Space Grotesk', 'Space Grotesk Light Bold', 'SpaceGrotesk-700.ttf', 'bold', 1.05, False),
    'roboto': ('Roboto', 'Roboto Black', 'Roboto-900.ttf', 'bold', 1.01, False),
    'open_sans': ('Open Sans', 'Open Sans ExtraBold', 'OpenSans-800.ttf', 'bold', 0.99, False),
    'lato': ('Lato', 'Lato Black', 'Lato-900.ttf', 'bold', 1.0, False),
    'work_sans': ('Work Sans', 'Work Sans ExtraBold', 'WorkSans-800.ttf', 'bold', 1.08, False),
    'bangers': ('Bangers', 'Bangers Regular', 'Bangers-400.ttf', 'fun', 0.85, False),
    'luckiest_guy': ('Luckiest Guy', 'Luckiest Guy Regular', 'LuckiestGuy-400.ttf', 'fun', 0.89, False),
    'titan_one': ('Titan One', 'Titan One', 'TitanOne-400.ttf', 'fun', 0.97, False),
    'lilita_one': ('Lilita One', 'Lilita One', 'LilitaOne-400.ttf', 'fun', 1.03, False),
    'bungee': ('Bungee', 'Bungee Regular', 'Bungee-400.ttf', 'fun', 0.87, False),
    'righteous': ('Righteous', 'Righteous', 'Righteous-400.ttf', 'fun', 1.02, False),
    'fredoka': ('Fredoka', 'Fredoka Light Bold', 'Fredoka-700.ttf', 'fun', 1.02, False),
    'chewy': ('Chewy', 'Chewy Regular', 'Chewy-400.ttf', 'fun', 0.96, False),
    'passion_one': ('Passion One', 'Passion One Regular', 'PassionOne-400.ttf', 'fun', 1.14, False),
    'russo_one': ('Russo One', 'Russo One', 'RussoOne-400.ttf', 'fun', 1.02, False),
    'black_ops': ('Black Ops One', 'Black Ops One Regular', 'BlackOpsOne-400.ttf', 'fun', 1.07, False),
    'press_start': ('Press Start 2P', 'Press Start 2P Regular', 'PressStart2P-400.ttf', 'fun', 0.83, False),
    'lobster': ('Lobster', 'Lobster Regular', 'Lobster-400.ttf', 'fun', 0.95, False),
    'baloo': ('Baloo 2', 'Baloo 2 ExtraBold', 'Baloo2-800.ttf', 'fun', 1.11, True),
    'modak': ('Modak', 'Modak', 'Modak-400.ttf', 'fun', 1.04, True),
    'permanent_marker': ('Permanent Marker', 'Permanent Marker Regular', 'PermanentMarker-400.ttf', 'hand', 0.91, False),
    'kaushan': ('Kaushan Script', 'Kaushan Script', 'KaushanScript-400.ttf', 'hand', 0.95, False),
    'caveat': ('Caveat', 'Caveat Bold', 'Caveat-700.ttf', 'hand', 1.06, False),
    'kalam': ('Kalam', 'Kalam Bold', 'Kalam-700.ttf', 'hand', 1.0, True),
    'pacifico': ('Pacifico', 'Pacifico Regular', 'Pacifico-400.ttf', 'hand', 0.92, False),
    'satisfy': ('Satisfy', 'Satisfy Regular', 'Satisfy-400.ttf', 'hand', 0.93, False),
    'gloria': ('Gloria Hallelujah', 'Gloria Hallelujah', 'GloriaHallelujah-400.ttf', 'hand', 0.99, False),
    'shadows': ('Shadows Into Light', 'Shadows Into Light', 'ShadowsIntoLight-400.ttf', 'hand', 0.93, False),
    'rock_salt': ('Rock Salt', 'Rock Salt Regular', 'RockSalt-400.ttf', 'hand', 0.8, False),
    'amita': ('Amita', 'Amita Bold', 'Amita-700.ttf', 'hand', 0.98, True),
    'playfair': ('Playfair Display', 'Playfair Display ExtraBold', 'PlayfairDisplay-800.ttf', 'serif', 1.02, False),
    'dm_serif': ('DM Serif Display', 'DM Serif Display Regular', 'DMSerifDisplay-400.ttf', 'serif', 1.1, False),
    'abril': ('Abril Fatface', 'Abril Fatface', 'AbrilFatface-400.ttf', 'serif', 1.06, False),
    'merriweather': ('Merriweather', 'Merriweather Light 18pt Black', 'Merriweather-900.ttf', 'serif', 0.96, False),
    'lora': ('Lora', 'Lora Bold', 'Lora-700.ttf', 'serif', 1.04, False),
    'lora_medium': ('Lora Medium', 'Lora Medium', 'Lora-500.ttf', 'serif', 1.04, False),
    'cinzel': ('Cinzel', 'Cinzel ExtraBold', 'Cinzel-800.ttf', 'serif', 0.96, False),
    'yeseva': ('Yeseva One', 'Yeseva One Regular', 'YesevaOne-400.ttf', 'serif', 1.04, False),
    'rozha': ('Rozha One', 'Rozha One Regular', 'RozhaOne-400.ttf', 'serif', 1.23, True),
    'tiro': ('Tiro Hindi', 'Tiro Devanagari Hindi Regular', 'TiroDevanagariHindi-400.ttf', 'serif', 1.06, True),
    'eczar': ('Eczar', 'Eczar ExtraBold', 'Eczar-800.ttf', 'serif', 1.09, True),
    'laila': ('Laila', 'Laila Bold', 'Laila-700.ttf', 'serif', 0.96, True),
    'mukta': ('Mukta', 'Mukta ExtraBold', 'Mukta-800.ttf', 'hindi', 1.13, True),
    'hind': ('Hind', 'Hind Bold', 'Hind-700.ttf', 'hindi', 1.06, True),
    'noto_deva': ('Noto Sans Devanagari', 'Noto Sans Devanagari ExtraBold', 'NotoSansDevanagari-800.ttf', 'hindi', 0.99, True),
    'teko': ('Teko', 'Teko SemiBold', 'Teko-600.ttf', 'hindi', 1.11, True),
    'rajdhani': ('Rajdhani', 'Rajdhani Bold', 'Rajdhani-700.ttf', 'hindi', 1.09, True),
    'khand': ('Khand', 'Khand Bold', 'Khand-700.ttf', 'hindi', 0.98, True),
    'martel_sans': ('Martel Sans', 'Martel Sans Black', 'MartelSans-900.ttf', 'hindi', 1.0, True),
    'yatra': ('Yatra One', 'Yatra One Regular', 'YatraOne-400.ttf', 'hindi', 1.04, True),
    'palanquin': ('Palanquin Dark', 'Palanquin Dark Bold', 'PalanquinDark-700.ttf', 'hindi', 1.07, True),
    'sarpanch': ('Sarpanch', 'Sarpanch ExtraBold', 'Sarpanch-800.ttf', 'hindi', 1.13, True),
    'gotu': ('Gotu', 'Gotu', 'Gotu-400.ttf', 'hindi', 0.99, True),
    'kurale': ('Kurale', 'Kurale Regular', 'Kurale-400.ttf', 'hindi', 1.11, True),
}


def get(key):
    """Font entry as a dict, or None for unknown keys (= the template's own font)."""
    if key not in FONTS:
        return None
    label, name, file, group, scale, hindi = FONTS[key]
    return {"key": key, "label": label, "name": name, "file": file, "group": group, "scale": scale, "hindi": hindi}


def catalog():
    """For the browser: everything the font picker needs."""
    return {"groups": GROUPS, "fonts": [get(k) for k in FONTS]}
