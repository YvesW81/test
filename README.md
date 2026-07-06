
open data van [NDW](https://opendata.ndw.nu/):


Draait via GitHub Actions (`.github/workflows/collect.yml`); elke run commit
de nieuwe snapshots naar deze repo.

## Data

- `snapshots_dc/status_YYYYMMDD_HHMM.csv.gz` — per snellaadpunt de status
- `snapshots_ac/status_YYYYMMDD_HHMM.csv.gz` — per regulier laadpunt de status
- `locations.csv.gz` — referentie: locatie, adres, coördinaten, operator en
  vermogen per laadpunt (wekelijks ververst)
- `collect.log` — logregel per run

Statussen (OCPI): AVAILABLE, CHARGING, BLOCKED, RESERVED, OUTOFORDER,
INOPERATIVE, REMOVED, UNKNOWN. Tijdstempels in bestandsnamen zijn UTC.

## Beheer

- Handmatig draaien: Actions-tab → "Collect laadpaal-statussen" → Run workflow
- Let op: GitHub schakelt scheduled workflows in publieke repo's uit na 60
  dagen zonder repo-activiteit; de bot-commits tellen doorgaans als activiteit,
  maar check af en toe de Actions-tab
- De repo groeit met ±14 MB per dag; archiveer/verplaats oude snapshots als
  dat na een paar maanden te veel wordt

