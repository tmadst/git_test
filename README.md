# Målscorer-model (La Liga + Premier League)

Prissætter **anytime-, første-, 2+- og 3+-målscorer** ud fra Pinnacles odds,
efter Bookie Bashing-metoden: start med kampens forventede mål (ikke spillerens
sidste 5 kampe), fordel dem på holdene, træk indskiftere og selvmål fra, og
fordel resten mellem de 10 startende markspillere.

## Opsætning (Positron)
1. Åbn mappen i Positron og vælg en Python 3.11+-fortolker (gerne et nyt venv).
2. `pip install -r requirements.txt`
3. Kopiér `.env.example` til `.env` og indsæt din `BETTINGISCOOL_API_KEY`.
4. `python update.py` — henter data for alle ligaer til `data/goalmodel.duckdb`
   (`--league laliga` / `--league epl` for kun én).
5. Åbn `analysis.py` og kør cellerne (Ctrl/Cmd+Enter).
   Databasen kan også åbnes i Positrons **Connections**-panel (DuckDB).

Kør `update.py` så tit du vil (fx morgen, et par timer før kampstart og efter
holdkort). Hver kørsel gemmer et nyt odds-snapshot for kommende kampe, så du
selv opbygger linjebevægelser over tid.

## Tokenforbrug (bettingiscool)
- Kampprogram: 1 kald pr. kørsel (~100 rækker).
- Spillede kampe: lukke-odds + slutresultat hentes **én gang** pr. kamp (~37 tokens).
- Kommende kampe: ét snapshot pr. kamp inden for `--days` (~25 tokens).
- Alle kald logges i tabellen `api_log` — hele sæsonen indtil nu kostede ~3.500 tokens.

## Pipeline
| Trin | Fil | Hvad |
|---|---|---|
| 1 | `goalmodel/ingest.py` | Kampe, lukke-odds, resultater og snapshots → DuckDB |
| 2 | `goalmodel/xg_fit.py` | Kampens xG: finder λ_hjemme/λ_ude (Poisson), hvis fair-priser bedst matcher Pinnacles vig-frie odds på **alle** linjer: 1X2, over/under (inkl. kvartlinjer), asiatisk handicap og holdtotaler |
| 3 | `goalmodel/goalscorer.py` | Fjerner indskifter-andel (14 %) og selvmål (3 %), fordeler resten på starterne efter position × multiplier eller markedets anytime-pris (inverse Poisson), og regner priser ud med Poisson |

Første målscorer = spillerens xG / kampens xG × P(mindst ét mål).

## Backtest af Pinnacles målscorer-odds
`python update.py --since 2025-08-01T00:00:00Z` henter også sidste sæson, og
`backtest.py` (Positron-celler) måler Pinnacles "X To Score"-props:
kalibrering (forventede vs. faktiske scorere), flad-ROI for Ja/Nej ved åbning
og lukning, linjebevægelse/CLV og spillernes implicitte xG. Vælg liga med `LEAGUE`
øverst i filen. Pinnacle lægger kun props op for få spillere (langt flere i
Premier League end i La Liga), og specials-data findes fra ca. sept. 2025.

## Tabeller
`fixtures`, `odds_closing`, `specials_closing`, `specials_history`, `odds_snapshots`, `results`, `match_xg`, `api_log`,
samt `players` og `lineups` (til at udfylde selv: startere og målscorere —
bruges til at kalibrere positionsandele, indskifterandel og afregne bets).
Views: `matches` (dubletter fjernet — Pinnacle lister nogle kampe under to
event-id'er) og `closing_main_total`.

## Næste skridt
- Pinnacles egne målscorer-props (`/api/specials`) som spillervægte — giver
  markedets ratio mellem spillerne i stedet for positions-gæt.
- Kalibrér `SUB_SHARE`, `OWN_GOAL_SHARE` og `POSITION_WEIGHT` på La Liga-data.
- Dixon-Coles-justering (Poisson undervurderer 0-0 og uafgjort en smule).
