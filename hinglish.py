#!/usr/bin/env python3
"""Rule-based Devanagari -> Hinglish (casual Roman Hindi) transliteration.

Whisper writes Hindi speech in Devanagari; this turns it into the spelling
people actually type ("aap kaise hain", "mujhe nahin pata") using Hindi
schwa-deletion rules rather than a strict academic scheme.
"""
import re

import hinglish_words

CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    # precomposed nukta letters
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f", "य़": "y",
}
NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f", "य": "y"}
VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
VIRAMA, NUKTA_SIGN = "्", "़"
NASALS = {"ं": "n", "ँ": "n"}
OTHER = {"ः": "h", "।": ".", "॥": ".", "ॐ": "om"}
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}

DEVANAGARI = re.compile(r"[ऀ-ॣ०-ॿ]+")      # words; the danda । is punctuation



def _key(word):
    """Spelling-insensitive lookup key: Whisper is loose with nukta, chandrabindu and ॉ."""
    return word.replace("\u093c", "").replace("ँ", "ं").replace("ॉ", "ो")


# Words whose everyday spelling doesn't follow the rules (see hinglish_words.py).
COMMON = {_key(dev): rom for dev, rom in hinglish_words.COMMON.items()}
for eng, spellings in hinglish_words.ENGLISH.items():
    for dev in spellings.split():
        COMMON.setdefault(_key(dev), eng)


def _syllables(word):
    """Split a Devanagari word into aksharas: dicts with cons, vowel, nasal."""
    out, i, n = [], 0, len(word)
    while i < n:
        ch = word[i]
        if ch in CONS:
            cluster = []
            while i < n and word[i] in CONS:
                c = CONS[word[i]]
                if i + 1 < n and word[i + 1] == NUKTA_SIGN:
                    c = NUKTA.get(word[i], c)
                    i += 1
                cluster.append(c)
                i += 1
                if i < n and word[i] == VIRAMA:
                    i += 1
                    if i < n and word[i] in CONS:
                        continue          # conjunct: keep collecting consonants
                    cluster.append("")    # explicit halant at word end
                break
            if cluster and cluster[-1] == "":
                out.append({"cons": cluster[:-1], "vowel": "", "inherent": False, "nasal": ""})
                continue
            syl = {"cons": cluster, "vowel": "a", "inherent": True, "nasal": ""}
            if i < n and word[i] in MATRAS:
                syl.update(vowel=MATRAS[word[i]], inherent=False)
                i += 1
            out.append(syl)
        elif ch in VOWELS:
            out.append({"cons": [], "vowel": VOWELS[ch], "inherent": False, "nasal": ""})
            i += 1
        elif ch in NASALS:
            if out:
                out[-1]["nasal"] = "n"
            i += 1
        else:
            out.append({"cons": [], "vowel": OTHER.get(ch, DIGITS.get(ch, "")), "inherent": False,
                        "nasal": "", "raw": True})
            i += 1
    return out


def _word(word, lists=True):
    k = _key(word)
    if lists and k in COMMON:
        return COMMON[k]
    for tail in ("्स", "स") if lists else ():           # plural of a listed English word: टास्क्स
        if k.endswith(tail) and k[:-len(tail)] in COMMON and COMMON[k[:-len(tail)]].isascii() \
                and COMMON[k[:-len(tail)]] in hinglish_words.ENGLISH:
            return COMMON[k[:-len(tail)]] + "s"
    syls = _syllables(word)
    letters = [s for s in syls if not s.get("raw")]
    if not letters:
        return "".join(s["vowel"] for s in syls)

    # Schwa deletion, right to left (Hindi drops the inherent 'a' in V C_ C V).
    # Final conjuncts keep the 'a' only when ending in y/r/v (mitra, kaarya).
    last = letters[-1]
    if (len(letters) > 1 and last["inherent"] and not last["nasal"]
            and (len(last["cons"]) == 1 or last["cons"][-1] not in ("y", "r", "v"))):
        last["vowel"] = ""
    for k in range(len(letters) - 2, 0, -1):
        s, prev, nxt = letters[k], letters[k - 1], letters[k + 1]
        if (s["inherent"] and s["vowel"] and not s["nasal"] and len(s["cons"]) == 1
                and prev["vowel"] and nxt["cons"] and nxt["vowel"]):
            s["vowel"] = ""

    # Casual-spelling tweaks for word endings.
    end = letters[-1]
    if end["cons"]:
        if end["vowel"] == "aa":
            end["vowel"] = "a"                       # tha, kya, karna
        elif end["vowel"] == "ee":
            end["vowel"] = "i"                       # bhi, nahi, ki
        elif end["vowel"] == "e" and end["nasal"]:
            end["vowel"] = "ei"                      # mein, hein
    elif end["vowel"] == "ee" and len(letters) > 1:
        end["vowel"] = "i"                           # kamaai, bhaai
    for s in letters:
        if s["vowel"] == "oo" and s["nasal"] and s is end:
            pass                                     # hoon
        elif s["vowel"] == "ee" and s["nasal"] and s is end:
            s["vowel"] = "i"                         # nahin

    out = "".join("".join(s["cons"]) + s["vowel"] + s["nasal"] for s in syls)
    out = re.sub(r"(?<=[^aeiou]i)e$", "ye", out)       # -इए endings: liye, chaliye, dekhiye
    out = re.sub(r"(?<=aa)e", "ye", out)                 # जाएंगे, आएगा: jaayenge, aayega
    return re.sub(r"(?<=\w)oon?g([aei])$", r"ung\1", out)  # करूंगा, करूगा: karunga


def to_hinglish(text, lists=True):
    """Transliterate every Devanagari run in text; leave Latin/punctuation as is.
    lists=False spells every word out by the rules alone, ignoring hinglish_words."""
    return DEVANAGARI.sub(lambda m: _word(m.group(0), lists), text).replace("।", ".").replace("॥", ".")


if __name__ == "__main__":
    import sys
    tests = sys.argv[1:] or ["आप कैसे हैं", "मुझे नहीं पता", "मैं घर जा रहा हूँ", "क्या बात है",
                             "समझना", "करना", "ज़िंदगी", "हम लोग अभी आ रहे हैं", "स्टेप मास्टर ऐप से कमाई",
                             "मिलेगा", "पैसे", "दोस्तों", "क्यों", "में", "भी"]
    for t in tests:
        print(f"{t}  ->  {to_hinglish(t)}")
