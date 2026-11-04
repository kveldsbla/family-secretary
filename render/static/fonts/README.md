# Fonter

Fontfilene ligger ikke i Git. Hent dem med:

    python hent_fonter.py           # laster ned og sjekker sjekksummen på hver fil
    python hent_fonter.py --sjekk   # bare sjekk det du har

| Fil | Font | Kilde | Hvordan den brukes |
|---|---|---|---|
| `CormorantGaramond-*.ttf` | Cormorant Garamond | smart-frame-tv, commit `b124b8e` | Bakes inn i HTML-en |
| `Jost-*.ttf` | Jost | smart-frame-tv, commit `b124b8e` | Bakes inn i HTML-en |
| `NotoColorEmoji-Regular.ttf` | Noto Color Emoji 2.055 (COLRv1) | google/fonts, commit `c08cd28` | Lenkes som lokal fil (ca. 25 MB, for stor til å bake inn) |

Alle er under SIL Open Font License 1.1. Lisenstekstene (`OFL-*.txt`) lastes ned sammen med fontene.
Adressene og sjekksummene står i `hent_fonter.py`.

Uten fonter her brukes systemfontene som reserve.
