.PHONY: dev install collect collect-xg status help

help:
	@echo "euro-top-stats — Commandes disponibles"
	@echo ""
	@echo "  make install      Installe les dépendances (venv + pip)"
	@echo "  make dev          Install + collecte initiale"
	@echo "  make collect      Collecte toutes les ligues (sans xG)"
	@echo "  make collect-xg   Collecte + xG Understat (top 5 ligues)"
	@echo "  make status       Statut DB et quota API"

install:
	pip install -e .

dev: install
	@echo ""
	@echo "📝 Copie le fichier .env :"
	@cp -n .env.example .env 2>/dev/null && echo "  .env créé depuis .env.example" || echo "  .env déjà existant"
	@echo ""
	@echo "⚠️  Renseigne ta clé API dans .env (API_FOOTBALL_KEY)"
	@echo "   Inscription gratuite : https://api-sports.io/"

collect:
	python scripts/collect.py --league all

collect-xg:
	python scripts/collect.py --league all --xg

status:
	euro-top status

rapport:
	euro-top rapport
