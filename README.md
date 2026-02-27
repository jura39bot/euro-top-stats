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

| Source | Usage | Coût | Lib |
|--------|-------|------|-----|
| [API-Football](https://api-sports.io/) | Résultats, classements, buteurs, passeurs, xG (saisons ≤ 2024) | Free (100 req/jour) | `httpx` |
| [Understat.com](https://understat.com) | xG par match, top 5 ligues, **saison courante incluse** | Gratuit | `understatapi` |
| [Sofascore](https://www.sofascore.com) | xG + stats match toutes compétitions, résultats temps réel | Gratuit (API non officielle) | `requests` |
| [The Odds API](https://the-odds-api.com) | Cotes pré-match +80 bookmakers, marchés 1X2/O-U/HC | Free (500 req/mois) | `requests` |

> ⚠️ **Saison courante (2025-2026)** : API-Football free plan bloqué sur saison ≤ 2024.
> Utiliser **Understat** (xG) ou **Sofascore** (xG + stats) pour la saison courante.

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

### Clé The Odds API (gratuite — pour les value bets)
1. Inscription sur [the-odds-api.com](https://the-odds-api.com)
2. Dashboard → API key
3. Dans `.env` : `ODDS_API_KEY=ton_token_ici`

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

### 🎰 Value bets (xG × cotes The Odds API)
```bash
# Value bets Ligue 1 (seuil 3% par défaut, 10 derniers matchs)
python3 scripts/value_bets.py --league ligue1

# Plusieurs ligues, seuil personnalisé, export JSON
python3 scripts/value_bets.py --league ligue1 pl laliga --min-value 5 --export

# Champions League (cotes uniquement, pas de xG disponible)
python3 scripts/value_bets.py --league cl
```

**Modèle :**
- Probabilités estimées via xG cumulé (N derniers matchs, modèle Poisson)
- Cotes meilleures disponibles parmi +80 bookmakers EU (Unibet, Betclic, Winamax, Pinnacle…)
- `Value = P(xG) − P(implicite)` — positif = bookmaker sous-évalue la probabilité réelle
- Espérance de valeur (EV) : `P(xG) × cote − 1`

> ⚠️ Outil d'analyse uniquement. Les marchés intègrent déjà partiellement le xG.
> Nécessite `ODDS_API_KEY` dans `.env` ([inscription gratuite](https://the-odds-api.com)).

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
  - ⚠️ Saison courante (2025-2026) **non accessible** en plan free — utiliser Understat ou Sofascore
- **xG par match** (`--stats`) : 1 req/match → à utiliser avec parcimonie (5-10 matchs max par run)
- **Distance (km) totale** : non disponible gratuitement (donnée Opta/tracking GPS, hors portée des APIs libres)
- **Understat** : xG gratuit, saison courante ✅ — **top 5 ligues uniquement** (pas CL/EL/ECL)
- **Sofascore** : API non officielle, peut changer sans préavis — préférer Understat pour les données de saison
- **The Odds API** : 500 req/mois en free (suffisant pour monitoring hebdo multi-ligues) — valeur des value bets limitée car les marchés intègrent déjà le xG
- **Modèle Poisson xG** : approximation simplifiée, à affiner avec données historiques plus riches

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
