# tv/

- `frame.py` og `state.py`: fra smart-frame-tv (MIT, commit `b124b8e`). Lokale endringer i `frame.py`:
  rettelse for kryptert opplasting (`secured`) og at verdien logges i stedet for å skrives ut.
- `upload.py`: vår kode. PNG → JPEG, tidsgrense på Art Mode-kanalen, opplasting, visning,
  rydding av forrige familiehub-bilde og `--undo`. Sletter bare bilder i `data/state.json`.
