# Family Secretary

A local, privacy-first assistant for busy families, running on a computer at home.

Every morning and afternoon it gathers the day's weather, the family calendar and the school holidays, works out what the children should wear and when they need to leave, and presents it all as a calm, readable picture. The first output channel is a Samsung Frame TV in Art Mode: the family's day hangs on the wall as a piece of art. More channels will follow.

> **Language:** the picture, the settings and the code comments are in Norwegian (bokmål). An English version may come later. A short Norwegian guide is at the end of this page.

## Principles

- **Local first.** Data stays at home; nothing depends on a subscription.
- **Readable by everyone.** Large type and icons that a four-year-old can follow.
- **Configurable.** Each family sets its own people, colours, places and rules, in one file.

## What the picture shows

- Today's weather from [Yr](https://www.yr.no) (MET Norway), with "feels like", rain and wind for the school day
- What to wear, as a checklist and as weather icons for the youngest
- The family calendar, with a colour and name for each person
- A family photo of the day (optional)
- From 18:00: tonight and tomorrow, in calm evening colours
- 08:00–08:10 on school days: "Nå må du dra!" ("Time to go!"), with only what the children need

## Status

Working prototype in daily use since November 2026. A hobby project, shared as it is: there is no promise of support.

| Tested with              | Version                                 |
| ------------------------ | --------------------------------------- |
| Samsung Frame Pro (2025) | firmware 1301, Art API 5.0.1.0          |
| Windows 10 Home          | Python 3.13, Google Chrome              |
| macOS, Raspberry Pi OS   | not tested yet (should work; see below) |

Other Frame models may need adjustments. Try `python oppsett.py --par` and `python main.py` on your own TV first.

## What you need

- A computer on the same home network as the TV: a Windows PC, a Mac or a Raspberry Pi
- [Python](https://www.python.org/downloads/) 3.13 and [Git](https://git-scm.com/downloads)
- Google Chrome (Windows, Mac) or Chromium (Raspberry Pi), used to draw the picture
- A Samsung Frame TV
- Optional: a shared calendar with a public or secret `.ics` link (iCloud, Google)

Everything used is free and available to private individuals. No accounts are needed except for the calendar you already have.

## Installation

Commands for **Windows PowerShell**. On a **Mac or Raspberry Pi**, use `python3` instead of `python` when creating the environment, and `.venv/bin/python` instead of `.venv\Scripts\python`.

```powershell
git clone https://github.com/kveldsbla/family-secretary.git
cd family-secretary
python -m venv .venv                                     # a private Python environment for this project
.venv\Scripts\python -m pip install -r requirements.txt  # the libraries, at tested versions
.venv\Scripts\python hent_fonter.py                      # the fonts (about 26 MB), checked against known checksums
.venv\Scripts\python oppsett.py                          # setup: answer the questions, connect the TV
```

`oppsett.py` asks for your home's coordinates, an e-mail address (MET Norway requires one), the TV's address, the people in the family and, optionally, the calendar link. It writes your settings and connects to the TV: put the TV in Art Mode and choose **Allow** when it asks.

Then try it:

```powershell
.venv\Scripts\python main.py --demo vinter --dry-run   # a demo picture in output\, nothing sent
.venv\Scripts\python main.py --dry-run                 # your real weather and calendar, nothing sent
.venv\Scripts\python main.py                           # make the picture and send it to the TV
.venv\Scripts\python main.py --undo                    # remove our pictures from the TV again
```

If Windows Firewall asks about Python, allow it on **private networks** only.

## Settings: one file

After setup, **`config.yaml` is the only file you need to open.** It holds your place, TV and people, with comments in Norwegian. Everything else has sensible defaults. To change more (clothing rules, times, texts), look up the setting in `config.example.yaml` and copy only the lines you want to change into `config.yaml`.

**Calendar tags.** Start an event's title with a person's initial to give it their colour: `L Football`, `E & L Parents' evening`. Events without an initial belong to the whole family.

**School holidays.** `skolerute.yaml` lists the days off school, when the "Time to go!" picture is not shown. Setup copies an example (a Norwegian municipality, 2026–28). Check the dates against your own school calendar.

**Photos.** Put landscape photos in the `bilder` folder; one is shown each day. The file name becomes the caption.

## Running it automatically

Each run picks the right picture from the clock, so a scheduler only needs to start `main.py` at fixed times (for example 08:00, 08:10 and 18:05). Note that each upload switches the TV to Art Mode, even if someone is watching.

- **Windows:** Task Scheduler (guide coming)
- **Raspberry Pi:** a `systemd` timer (guide coming)

Exit codes: `0` OK, `1` error, `2` the TV did not answer (try again later).

## Privacy

Your settings (`config.yaml`), the calendar link (`.env`), the TV key (`data/`), photos, pictures and logs stay on your computer and are listed in `.gitignore`. The program contacts only MET Norway (weather), your calendar link and the TV on your home network.

## Acknowledgements

The Samsung Frame upload is built on [smart-frame-tv](https://github.com/Seagey/smart-frame-tv) (MIT licence), with a fix for encrypted uploads on the Frame Pro. Thank you for the groundwork.

- TV connection: [samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api) (MIT)
- Weather data: [MET Norway](https://api.met.no), CC BY 4.0
- Fonts: Cormorant Garamond, Jost and Noto Color Emoji, all under the SIL Open Font License; downloaded by `hent_fonter.py`, not included here

## Licence

Family Secretary is free software under the [GNU General Public License v3.0](LICENSE): you may use, change and share it, but changed versions you share must use the same licence and keep the credits.

`tv/frame.py` and `tv/state.py` come from smart-frame-tv and remain under the MIT licence; see [`LICENSES/smart-frame-tv-MIT.txt`](LICENSES/smart-frame-tv-MIT.txt).

## Norsk kortversjon

Family Secretary lager et rolig bilde av familiens dag (vær, klesråd, kalender og «Nå må du dra!») og viser det i Art Mode på en Samsung Frame. Alt kjører hjemme, uten abonnement.

1. Installer Python 3.13, Git og Google Chrome.
2. Kjør kommandoene under «Installation» i PowerShell.
3. `oppsett.py` stiller spørsmålene og kobler til TV-en (sett TV-en i Art Mode og velg «Tillat»).
4. Etterpå er `config.yaml` det eneste dokumentet du trenger å endre. `config.example.yaml` viser alt som kan stilles inn.

Hobbyprosjekt, delt som det er, uten løfte om support.

## Author

Created by kveldsbla, Norway, 2026.
