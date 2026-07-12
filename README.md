# Parcel Tracker

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/MaximeBranger/parcel-tracker/actions/workflows/validate.yaml/badge.svg)](https://github.com/MaximeBranger/parcel-tracker/actions/workflows/validate.yaml)

Intégration Home Assistant distribuée via [HACS](https://hacs.xyz) permettant de centraliser le suivi de tous vos colis, quel que soit le transporteur.

Le MVP fonctionne de manière autonome, sans service externe : il interroge directement l'API de La Poste (Colissimo, Chronopost, lettre suivie) et stocke les données localement dans `.storage/`.

Voir [SPECIFICATIONS.md](SPECIFICATIONS.md) pour la spécification complète.

Une carte Lovelace dédiée, optionnelle, existe dans le dépôt séparé [`parcel-tracker_card`](https://github.com/MaximeBranger/parcel-tracker_card).

## Installation

Via [HACS](https://hacs.xyz), en ajoutant ce dépôt comme dépôt personnalisé (catégorie « Integration »).

## Configuration

L'intégration nécessite une clé développeur pour l'API Suivi de La Poste, à saisir lors de l'ajout de l'intégration. Créez un compte gratuit et une application sur [developer.laposte.fr](https://developer.laposte.fr) pour l'obtenir.

## Tester l'intégration en mode développement

Pas besoin d'installer une instance Home Assistant complète séparée : on lance une instance de développement locale qui charge directement ce dépôt via `custom_components/`.

### 1. Préparer un environnement Home Assistant local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install homeassistant
```

### 2. Créer un dossier de config et y lier l'intégration

```bash
mkdir -p config/custom_components
ln -s "$(pwd)/custom_components/parcel_tracker" config/custom_components/parcel_tracker
```

Le lien symbolique permet de modifier le code du dépôt et de le retrouver directement pris en compte au prochain redémarrage de Home Assistant, sans copie manuelle.

### 3. Activer les logs de debug de l'intégration

Ajoutez dans `config/configuration.yaml` (généré automatiquement au premier lancement, sinon créez-le) :

```yaml
logger:
  default: info
  logs:
    custom_components.parcel_tracker: debug
```

### 4. Lancer Home Assistant

```bash
hass -c config
```

Au premier lancement, l'assistant de configuration se termine sur `http://localhost:8123`. Terminez l'onboarding (compte utilisateur, localisation...).

### 5. Ajouter l'intégration

Dans l'interface : **Paramètres → Appareils et services → Ajouter une intégration → Parcel Tracker**, puis saisissez votre clé API La Poste. La clé est validée par un appel de test au moment de la soumission (voir `config_flow.py`) ; une clé invalide affiche une erreur sans créer l'entrée.

### 6. Piloter les colis

Les colis ne passent pas par un flow de configuration séparé (une seule config entry par installation), mais peuvent être gérés de deux façons équivalentes :

* **Interface** : **Paramètres → Appareils et services → Parcel Tracker → Configurer** ouvre un menu permettant d'ajouter un colis, puis de le modifier (nom, notes, numéro de suivi — sans recréer son entité ni son historique), de l'archiver ou de le supprimer.
* **Services**, pour l'automatisation ou les tests rapides via **Outils de développement → Actions** : `parcel_tracker.add`, `.update`, `.remove`, `.archive`, `.refresh`, `.get_history`.

```yaml
action: parcel_tracker.add
data:
  tracking_number: "8Q00000000000"   # numéro de test fourni par La Poste
  name: "Colis de test"
```

Vérifiez ensuite :

* l'entité `sensor.<nom_du_colis>` apparaît immédiatement (sans redémarrage, grâce au dispatcher HA) ;
* les capteurs globaux (`sensor.parcels_active`, etc.) se mettent à jour ;
* l'onglet **Journal** affiche les événements (`parcel_added`, `parcel_updated`, ...) ;
* `parcel_tracker.refresh` force un cycle immédiat sans attendre les 15 minutes par défaut ;
* `parcel_tracker.get_history` (avec « Renvoyer la réponse » activé dans Outils de développement → Actions) retourne la liste des colis stockés.

### 7. Itérer

Toute modification du code Python nécessite un redémarrage de Home Assistant (`Ctrl+C` puis `hass -c config`). Pour valider rapidement une modification sans relancer toute l'instance, `hass -c config --script check_config` vérifie la configuration sans démarrer le cœur applicatif.

Les données des colis sont persistées dans `config/.storage/parcel_tracker` ; supprimez ce fichier pour repartir d'un état propre entre deux sessions de test.

## License

MIT — voir [LICENSE](LICENSE).
