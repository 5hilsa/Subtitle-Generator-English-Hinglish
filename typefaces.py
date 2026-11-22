#!/usr/bin/env python3
"""The caption font library. Every font here ships in ./fonts, so exports look the
same on Mac, Windows and the server, with no internet needed at export time.

All are from Google Fonts under the SIL Open Font License or Apache 2.0 (both
allow commercial use); each font's licence is in fonts/licenses/. Files are
static TTFs with Latin and, where the font has it, Devanagari.

  name   the font's full name inside the file (what libass matches on)
  scale  size correction so every font looks about as big as Poppins
  hindi  True if it can draw Devanagari (Hindi script)

Users can add more Google Fonts with "Match from image" (fontmatch.py). Those are
kept in DATA_DIR/fonts with added.json, and copied into ./fonts at start-up so the
browser and libass find them like any other.
"""
import json, os, re, shutil, threading

import config

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
ADDED_DIR = os.path.join(config.DATA_DIR, "fonts")
ADDED_INDEX = os.path.join(ADDED_DIR, "added.json")
WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
                600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}

GROUPS = {"bold": "Bold & clean", "fun": "Fun & display", "hand": "Handwritten",
          "serif": "Serif & elegant", "hindi": "Made for Hindi", "added": "Added"}

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


def _load_added():
    """{key: (label, name, file, group, scale, hindi, owner)}; owner is None for Google Fonts
    (shared by everyone) or the user id for a font file someone uploaded (theirs only)."""
    try:
        with open(ADDED_INDEX, encoding="utf-8") as f:
            added = {k: tuple(v) + (None,) * (7 - len(v)) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}
    for key, v in list(added.items()):
        dst = os.path.join(FONTS_DIR, v[2])
        if not os.path.isfile(dst):
            try:
                shutil.copyfile(os.path.join(ADDED_DIR, v[2]), dst)
            except OSError:
                del added[key]                   # its file is gone
    return added


ADDED = _load_added()
_lock = threading.Lock()


def get(key):
    """Font entry as a dict, or None for unknown keys (= the template's own font)."""
    entry = FONTS.get(key) or ADDED.get(key)
    if not entry and key and key.startswith(("gf_", "up_")):   # added in another server process
        ADDED.update(_load_added())
        entry = ADDED.get(key)
    if not entry:
        return None
    label, name, file, group, scale, hindi = entry[:6]
    return {"key": key, "label": label, "name": name, "file": file, "group": group, "scale": scale, "hindi": hindi}


def catalog(uid=None):
    """For the browser: everything the font picker needs (with this user's uploaded fonts)."""
    added = [k for k, v in ADDED.items() if v[6] is None or v[6] == uid]
    return {"groups": GROUPS, "fonts": [get(k) for k in list(FONTS) + added]}


def _describe(path):
    """(full name, scale, hindi) of a font file, measured the same way as the built-in fonts."""
    import uharfbuzz as hb
    face = hb.Face(hb.Blob.from_file_path(path))
    font = hb.Font(face)

    def cap(f, upem):
        g = f.get_nominal_glyph(ord("H"))
        ext = f.get_glyph_extents(g) if g else None
        return -ext.height / upem if ext and ext.height else 0.7
    poppins = hb.Face(hb.Blob.from_file_path(os.path.join(FONTS_DIR, FONTS["poppins"][2])))
    scale = round(min(1.3, max(0.75, cap(hb.Font(poppins), poppins.upem) / cap(font, face.upem))), 2)
    hindi = all(font.get_nominal_glyph(c) for c in (0x0915, 0x093E, 0x094D, 0x0939))
    return face.get_name(4) or face.get_name(1), scale, hindi, face


def _register(key, path, file, label, owner):
    name, scale, hindi, _ = _describe(path)
    with _lock:
        os.makedirs(ADDED_DIR, exist_ok=True)
        shutil.copyfile(path, os.path.join(ADDED_DIR, file))
        shutil.copyfile(path, os.path.join(FONTS_DIR, file))
        ADDED[key] = (label, name, file, "added", scale, hindi, owner)
        with open(ADDED_INDEX, "w", encoding="utf-8") as f:
            json.dump(ADDED, f, indent=1)
    return get(key)


def add(path, family, weight):
    """Add a downloaded Google Fonts TTF to the library (for everyone); returns its entry."""
    key = "gf_" + re.sub(r"[^a-z0-9]+", "_", family.lower()).strip("_") + f"_{weight}"
    if key in FONTS or key in ADDED:
        return get(key)
    label = family + ("" if weight == 400 else f" {WEIGHT_NAMES.get(weight, weight)}")
    return _register(key, path, f"gf-{re.sub(r'[^A-Za-z0-9]', '', family)}-{weight}.ttf", label, None)


def upload(path, uid):
    """Add a font file the user uploaded (a font they own). Only they see it, since the
    licence of a bought font is theirs, not everyone's. Raises ValueError if it isn't a font."""
    import hashlib
    try:
        name, _, _, face = _describe(path)
    except Exception:
        raise ValueError("That file isn't a font we can read. Use a .ttf or .otf file.")
    if not face.upem or not name:
        raise ValueError("That file isn't a font we can read. Use a .ttf or .otf file.")
    digest = hashlib.sha1(open(path, "rb").read()).hexdigest()[:12]
    key = f"up_{digest}_{re.sub(r'[^a-z0-9]+', '_', str(uid).lower())[:24]}"
    if key in ADDED:
        return get(key)
    ext = ".otf" if open(path, "rb").read(4) == b"OTTO" else ".ttf"
    return _register(key, path, f"up-{digest}{ext}", name, uid)
