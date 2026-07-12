# Parcel Tracker

Intégration Home Assistant distribuée via [HACS](https://hacs.xyz) permettant de centraliser le suivi de tous vos colis, quel que soit le transporteur.

Le MVP fonctionne de manière autonome, sans service externe : il interroge directement l'API de La Poste (Colissimo, Chronopost, lettre suivie) et stocke les données localement dans `.storage/`.

Voir [SPECIFICATIONS.md](SPECIFICATIONS.md) pour la spécification complète.

Une carte Lovelace dédiée, optionnelle, existe dans le dépôt séparé [`parcel-tracker_card`](https://github.com/MaximeBranger/parcel-tracker_card).

## Installation

Via [HACS](https://hacs.xyz), en ajoutant ce dépôt comme dépôt personnalisé (catégorie « Integration »).

## Configuration

L'intégration nécessite une clé développeur pour l'API Suivi de La Poste, à saisir lors de l'ajout de l'intégration.

## License

MIT — voir [LICENSE](LICENSE).
