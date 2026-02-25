# euro-top-stats ⚽🏆

**CLI Python pour les stats du football européen** — top 5 ligues + compétitions UEFA.

Buteurs, passeurs, xG (Expected Goals), distance couverte (km), classements et résultats.

---

## Ligues couvertes

| Ligue | Code CLI | Flag |
|-------|----------|------|
| Ligue 1 | `ligue1` / `fr` | 🇫🇷 |
| Premier League | `pl` / `en` | 🏴󠁧󠁢󠁥󠁮󠁧󠁿 |
| La Liga | `laliga` / `es` | 🇪🇸 |
| Serie A | `seriea` / `it` | 🇮🇹 |
| Bundesliga | `bundesliga` / `de` | 🇩🇪 |
| Champions League | `cl` | 🏆 |
| Europa League | `el` | 🟠 |
| Conference League | `ecl` | ⚪ |

---

## Sources de données

| Source | Usage | Coût |
|--------|-------|------|
| [API-Football](https://api-sports.io/) | Résultats, classements, buteurs, passeurs, xG (match), km | Free (100 req/jour) |
| [Understat.com](https://understat.com) | xG par match top 5 ligues | Gratuit (scraping) |

---

## Installation

```bash
git clone https://github.com/jura39bot/euro-top-stats.git
cd euro-top-stats

pip install -e .

cp .env.example .env
# Édite .env et renseigne ta clé API-Football
# Inscription gratuite sur https://api-sports.io/
```

### Clé API-Football (gratuite)
1. Inscription sur [api-sports.io](https://api-sports.io/)
2. Dashboard → ton token
3. Dans `.env` : `API_FOOTBALL_KEY=ton_token_ici`

---

## Quick Start

```bash
# Collecte initiale (toutes ligues, ~30-40 req)
euro-top collect --league all

# Avec xG depuis Understat (top 5 ligues, aucune req API)
euro-top collect --league all --xg

# Statut quota API
euro-top status
```

---

## Commandes

### 🏆 Classement
```bash
euro-top classement --league ligue1
euro-top classement --league pl --season 2023
euro-top classement --league cl
```

### 📋 Résultats récents
```bash
euro-top resultats --league bundesliga --last 10
euro-top resultats --league el
```

### ⚽ Top buteurs
```bash
euro-top buteurs --league laliga --top 20
euro-top buteurs --league cl
euro-top buteurs --league seriea --top 10
```

### 🎯 Top passeurs
```bash
euro-top passeurs --league pl --top 15
euro-top passeurs --league ecl
```

### 📊 xG — Expected Goals
```bash
# xG des 10 derniers matchs
euro-top xg --league ligue1 --last 10

# xG cumulé par équipe sur la saison
euro-top xg --league laliga --team

# xG Champions League
euro-top xg --league cl --last 20
```

### 🏃 Distance couverte (km)
```bash
# Moyenne km par équipe sur les 10 derniers matchs
euro-top distance --league pl --last 10
euro-top distance --league bundesliga --last 5
```

> ⚠️ Les données de distance (km) nécessitent les stats par match via `--stats`.
> Chaque match coûte 1 requête API.

### 📰 Rapport récap toutes ligues
```bash
euro-top rapport
```

### 📥 Collecte des données
```bash
# Toutes ligues (classement + résultats + buteurs + passeurs)
euro-top collect --league all

# Ligue spécifique
euro-top collect --league pl

# + xG via Understat (top 5 seulement, gratuit)
euro-top collect --league all --xg

# + stats par match (xG + km via API, coûteux en quota)
euro-top collect --league ligue1 --stats --last 5
```

---

## Exemples de sorties

### Classement Ligue 1
```
🇫🇷 Classement Ligue 1 — Saison 2024/2025
┌───┬──────────────────────┬───┬───┬───┬───┬────┬────┬──────┬─────┬─────────────────┐
│ # │ Équipe               │ J │ G │ N │ P │ BP │ BC │ Diff │ Pts │ Forme           │
├───┼──────────────────────┼───┼───┼───┼───┼────┼────┼──────┼─────┼─────────────────┤
│ 1 │ Paris Saint-Germain  │25 │18 │ 3 │ 4 │ 56 │ 27 │ +29  │  57 │ WWLWW           │
│ 2 │ Marseille            │25 │16 │ 5 │ 4 │ 48 │ 25 │ +23  │  53 │ WWWDW           │
│ 3 │ Monaco               │25 │14 │ 6 │ 5 │ 44 │ 30 │ +14  │  48 │ DWWWW           │
```

### xG par équipe (La Liga)
```
🇪🇸 xG par équipe — La Liga 2024/2025
┌────┬──────────────────────┬────────┬──────────┬───────────┬───────────┬───────────┬──────────┐
│  # │ Équipe               │ Matchs │  xG For  │ xG /match │ xG Against│ xGA/match │  Diff xG │
├────┼──────────────────────┼────────┼──────────┼───────────┼───────────┼───────────┼──────────┤
│  1 │ Barcelona            │     25 │    51.23 │      2.05 │     19.34 │      0.77 │   +31.89 │
│  2 │ Real Madrid          │     25 │    48.76 │      1.95 │     22.10 │      0.88 │   +26.66 │
```

### Distance couverte (Premier League)
```
🏴󠁧󠁢󠁥󠁮󠁧󠁿 Distance couverte — Premier League (moy. 10 derniers matchs)
┌───┬──────────────────────┬────────┬──────────┬──────────┬──────────────────┐
│ # │ Équipe               │ Matchs │  Moy. km │ Total km │       Intensité  │
├───┼──────────────────────┼────────┼──────────┼──────────┼──────────────────┤
│ 1 │ Brighton             │     10 │    115.4 │   1154.0 │ █████████████░   │
│ 2 │ Liverpool            │     10 │    113.8 │   1138.0 │ ████████████░░   │
```

---

## Structure du projet

```
euro-top-stats/
├── euro_top/
│   ├── config.py              # Ligues, IDs API-Football, aliases CLI
│   ├── db.py                  # SQLite via SQLAlchemy (sync)
│   └── collectors/
│       ├── api_football.py    # Client API-Football (httpx)
│       └── understat.py       # Scraper xG Understat
├── cli/
│   └── main.py               # CLI Typer + Rich
├── scripts/
│   └── collect.py            # Script collecte standalone (cron)
├── .env.example
├── Makefile
└── requirements.txt
```

---

## Cron — collecte automatique

```bash
# Collecte quotidienne à 7h (toutes ligues + xG)
0 7 * * * cd /root/Projects/euro-top-stats && euro-top collect --league all --xg >> /var/log/euro-top.log 2>&1
```

---

## Limites

- **API-Football free** : 100 req/jour — suffisant pour classements + buteurs + passeurs (≈32 req pour les 8 ligues)
- **xG par match** (`--stats`) : 1 req/match → à utiliser avec parcimonie (5-10 matchs max par run)
- **Distance (km)** : disponible uniquement via `--stats` (API par match) ou certains plans payants
- **Understat** : xG gratuit mais **top 5 ligues uniquement** (pas CL/EL/ECL)

---

## Makefile

```bash
make install      # pip install -e .
make dev          # install + guide setup
make collect      # collecte toutes ligues
make collect-xg   # collecte + xG Understat
make rapport      # affiche rapport toutes ligues
make status       # quota API + statut DB
```
