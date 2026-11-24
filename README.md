# cine.ar-scraper

> [!NOTE]
> Archived: published for conservation purposes. Not maintained.

Scrapes the [cine.ar](https://play.cine.ar) catalogue API by ID into a SQLite
database (`movies_shows.db`). Set `CINEAR_AUTH_TOKEN` ("Bearer ...") and
`CINEAR_PERFIL_ID` from a logged-in browser session (see comments in
`scraper.py`). `get_keys.py` lists every JSON key seen in the scraped responses.
