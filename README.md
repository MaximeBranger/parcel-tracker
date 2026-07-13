# Parcel Tracker

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/MaximeBranger/parcel-tracker/actions/workflows/validate.yaml/badge.svg)](https://github.com/MaximeBranger/parcel-tracker/actions/workflows/validate.yaml)

Intégration Home Assistant distribuée via [HACS](https://hacs.xyz) permettant de centraliser le suivi de tous vos colis, quel que soit le transporteur.

L'intégration fonctionne de manière autonome, sans service externe : elle interroge directement l'API de chaque transporteur configuré et stocke les données localement dans `.storage/`. Transporteurs pris en charge : **La Poste** (Colissimo, Chronopost, lettre suivie), **FedEx**, **DHL**, **UPS**, **Mondial Relay**, **PostNord**, **DPD**.

Voir [SPECIFICATIONS.md](SPECIFICATIONS.md) pour la spécification complète.

Une carte Lovelace dédiée, optionnelle, existe dans le dépôt séparé [`parcel-tracker_card`](https://github.com/MaximeBranger/parcel-tracker_card).

## Installation

Via [HACS](https://hacs.xyz), en ajoutant ce dépôt comme dépôt personnalisé (catégorie « Integration »).

## Configuration

Lors de l'ajout de l'intégration, saisissez les identifiants développeur du ou des transporteurs que vous voulez suivre — tous sont optionnels, mais au moins un est requis. Vous pourrez en ajouter ou en corriger plus tard sans recréer l'intégration, via **Paramètres → Appareils et services → Parcel Tracker → Reconfigurer**.

Aucune clé n'est fournie ou partagée par le projet : chacun crée ses propres identifiants directement chez le transporteur (comptes développeur gratuits, hors Mondial Relay et DPD). Ne les partagez pas et ne les commitez jamais dans un dépôt public.

| Transporteur  | Où obtenir les identifiants                                                | Identifiants demandés               |
|---------------|-----------------------------------------------------------------------------|--------------------------------------|
| La Poste      | [developer.laposte.fr](https://developer.laposte.fr) (compte gratuit)       | Clé API                              |
| FedEx         | [developer.fedex.com](https://developer.fedex.com), créer un projet Track API | Client ID + Client secret           |
| DHL           | [developer.dhl.com](https://developer.dhl.com), API « Shipment Tracking - Unified » | Clé API                       |
| UPS           | [developer.ups.com](https://developer.ups.com), créer une app avec le scope Track | Client ID + Client secret     |
| Mondial Relay | Compte marchand Mondial Relay (identifiants webservice WSI2)                | Login (Enseigne) + Clé privée       |
| PostNord      | [developer.postnord.com](https://developer.postnord.com) (compte gratuit)   | Clé API                              |
| DPD           | Compte professionnel DPD Group (identifiants GeoService)                    | Login + Mot de passe                 |

Chaque colis suivi choisit ensuite son transporteur parmi ceux configurés, à l'ajout ou à la modification. Le détail des étapes pour obtenir chaque identifiant est ci-dessous.

### La Poste

1. Créez un compte gratuit sur [developer.laposte.fr](https://developer.laposte.fr).
2. Une fois connecté, rendez-vous dans **Mes applications** et créez une nouvelle application.
3. Depuis la page de l'application, souscrivez à l'API **Suivi** (« Track & Trace »).
4. Récupérez la **clé API** générée pour l'application (souvent affichée comme `X-Okapi-Key`) : c'est la valeur à saisir dans le champ *Clé API* de l'intégration.

### FedEx

1. Créez un compte sur le [portail développeur FedEx](https://developer.fedex.com).
2. Dans le tableau de bord, cliquez sur **Create a new project**.
3. Ajoutez l'API **Track API** au projet créé.
4. Ouvrez l'onglet **Authentication** du projet : vous y trouverez l'**API Key** (à saisir comme *Client ID*) et la **Secret Key** (à saisir comme *Client secret*).
5. Ces identifiants pointent d'abord vers l'environnement sandbox de FedEx. Suivez la procédure « Move to Production » du portail pour obtenir des identifiants de production une fois vos tests validés — l'intégration fonctionne avec l'un ou l'autre, seules les données de suivi diffèrent (données fictives en sandbox).

### DHL

1. Créez un compte sur [developer.dhl.com](https://developer.dhl.com).
2. Dans **My Apps & Keys**, créez une nouvelle application (« Create App »).
3. Associez l'API **Shipment Tracking - Unified** à cette application.
4. Copiez la **Consumer Key** générée : c'est la clé API à renseigner dans l'intégration.
5. L'offre gratuite du portail DHL est soumise à un quota d'appels journalier — vérifiez les conditions affichées sur votre application si vous suivez beaucoup de colis avec un intervalle de rafraîchissement court.

### UPS

1. Créez un compte sur [developer.ups.com](https://developer.ups.com).
2. Depuis **Apps**, créez une nouvelle application (« Add Apps ») et sélectionnez le produit/scope **Track API**.
3. Un **Client ID** et un **Client secret** sont générés pour l'application : ce sont les deux valeurs attendues par l'intégration.
4. Comme pour FedEx, les identifiants créés par défaut ciblent l'environnement de test (CIE) d'UPS. Un accès en production peut nécessiter de lier l'application à un numéro de compte UPS existant, selon les conditions actuelles du portail.

### Mondial Relay

Mondial Relay n'a pas de portail développeur en libre-service : l'accès au webservice de suivi (WSI2) est réservé aux comptes marchands.

1. Contactez le service commercial Mondial Relay (ou votre interlocuteur habituel si vous avez déjà un compte marchand) pour demander l'activation du **webservice WSI2**.
2. Vous recevrez un **numéro d'enseigne** (identifiant marchand) : c'est le *Login* attendu par l'intégration.
3. Vous recevrez également une **clé privée** associée à ce compte, utilisée pour signer les requêtes : c'est la *Clé privée* attendue par l'intégration.
4. N'ayant pas d'environnement de test public, la validation des identifiants dans l'intégration se fait directement contre vos identifiants réels — assurez-vous qu'ils sont corrects avant de les saisir pour éviter des erreurs d'authentification répétées.

### PostNord

1. Créez un compte gratuit sur [developer.postnord.com](https://developer.postnord.com).
2. Souscrivez au produit **Track & Trace** (plan gratuit disponible en production, pas seulement en sandbox).
3. Récupérez la **clé API** générée : c'est la valeur à saisir dans le champ *Clé API PostNord* de l'intégration.
4. PostNord ne publie pas de liste exhaustive de ses statuts de colis ; seuls quelques statuts sont mappés dans `providers/postnord.py`, les autres retombent sur « en transit » — signalez tout statut mal interprété observé en usage réel.

### DPD

Comme Mondial Relay, DPD n'a pas de portail développeur en libre-service : l'accès à l'API de suivi (GeoService) est réservé aux comptes professionnels DPD Group.

1. Contactez votre interlocuteur commercial DPD Group (ou le support DPD si vous avez déjà un compte expéditeur) pour demander l'activation de l'accès **GeoService**.
2. Vous recevrez un **login** et un **mot de passe** : ce sont les valeurs attendues par l'intégration (*Identifiant DPD* / *Mot de passe DPD*).
3. N'ayant pas d'environnement de test public, la validation se fait directement contre vos identifiants réels — assurez-vous qu'ils sont corrects avant de les saisir pour éviter des erreurs d'authentification répétées.
4. Le contrat GeoService n'étant pas documenté publiquement, `providers/dpd.py` est une implémentation best-effort (mêmes réserves que Mondial Relay) : signalez tout comportement inattendu observé avec de vrais identifiants pour affiner le mapping des statuts.

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

Dans l'interface : **Paramètres → Appareils et services → Ajouter une intégration → Parcel Tracker**, puis saisissez les identifiants d'au moins un transporteur (voir [Configuration](#configuration)). Chaque transporteur renseigné est validé par un appel de test au moment de la soumission (voir `config_flow.py`) ; des identifiants invalides affichent une erreur sur le champ concerné sans créer l'entrée. Exception : **La Poste** n'a pas de numéro de suivi valable à la fois en sandbox et en production, donc sa clé n'est pas pré-validée — une clé invalide ne sera détectée qu'au premier suivi réel (logs + événement `parcel_error`).

### 6. Piloter les colis

Les colis ne passent pas par un flow de configuration séparé (une seule config entry par installation), mais peuvent être gérés de deux façons équivalentes :

* **Interface** : **Paramètres → Appareils et services → Parcel Tracker → Configurer** ouvre un menu permettant d'ajouter un colis, puis de le modifier (nom, notes, numéro de suivi — sans recréer son entité ni son historique), de l'archiver ou de le supprimer.
* **Services**, pour l'automatisation ou les tests rapides via **Outils de développement → Actions** : `parcel_tracker.add`, `.update`, `.remove`, `.archive`, `.refresh`, `.get_history`.

```yaml
action: parcel_tracker.add
data:
  tracking_number: "8Q00000000000"   # numéro de test La Poste (sandbox uniquement, échoue avec une clé de prod)
  name: "Colis de test"
```

Avec une clé La Poste de production, remplacez ce numéro par un vrai numéro de suivi Colissimo/Chronopost : les numéros de test documentés par La Poste ne fonctionnent qu'avec une clé sandbox.

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
