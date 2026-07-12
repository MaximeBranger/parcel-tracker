# Home Assistant Parcel Tracker — Spécifications (actualisées)

> Ce document remplace `SPECS.md` comme référence pour le MVP. Il résulte d'une session de clarification qui a tranché plusieurs points laissés ambigus ou contradictoires dans les documents précédents.
>
> `SPECS-API.md` et `VEILLE-API.md` restent valides comme **vision long terme** (une API de suivi mutualisée, multi-clients), mais décrivent une évolution **V3+**, pas le MVP : voir [Roadmap](#roadmap). `FRANCE-API.md` reste la référence pour le choix et la priorisation des transporteurs.

---

## Vision

Créer une intégration **Home Assistant** distribuée via **HACS** permettant de centraliser le suivi de tous les colis (réception et expédition), quel que soit le transporteur.

L'utilisateur ajoute simplement un numéro de suivi, puis l'intégration récupère automatiquement les informations du transporteur afin de :

* Suivre les colis en cours
* Consulter leur statut actuel
* Visualiser leur historique
* Exploiter les données dans Home Assistant (automatisations, tableaux de bord, statistiques)

---

## Décision d'architecture — MVP autonome, sans service externe

Le MVP est une **intégration HACS autonome** :

```text
Home Assistant
      │
      ▼
custom_components/parcel_tracker
      │
      ▼
Provider La Poste (API Suivi)
```

Il n'y a **aucun service à déployer séparément** (pas de FastAPI, PostgreSQL ou Redis au MVP). L'intégration interroge directement l'API du transporteur et stocke ses données dans `.storage/`, conformément au principe « sans cloud propriétaire ».

L'architecture multi-clients (API REST partagée, extension navigateur, app mobile) décrite dans `SPECS-API.md` et `VEILLE-API.md` reste l'évolution cible à long terme, mais n'est pas requise pour livrer un MVP utile. Elle est repositionnée en **V3** (voir [Roadmap](#roadmap)).

### Un package HACS autonome

Ce dépôt (`parcel_tracker`) est l'intégration backend — détection/suivi, entités, services, événements. Elle fonctionne seule, sans aucune dépendance frontend, et un utilisateur peut se contenter des cartes HA standards (entities, glance, markdown) pour composer son dashboard.

Une carte Lovelace dédiée existe en package HACS séparé, avec ses propres spécifications : voir le dépôt `parcel-tracker_card`.

---

## Périmètre du MVP

### Gestion des colis

#### Ajouter un colis

Informations :

* Numéro de suivi
* Nom personnalisé (ex. : *Commande Amazon*)
* Transporteur — figé sur **La Poste / Colissimo / Chronopost** au MVP (voir [Providers](#providers))
* Date d'ajout
* Notes (optionnel)

#### Modifier un colis

L'utilisateur peut modifier :

* le nom
* les notes
* le numéro de suivi
* le transporteur *(dès qu'un second provider existe)*

Modifier le numéro de suivi **ne recrée pas l'entité** — voir [Identité de l'entité](#identité-de-lentité).

#### Supprimer un colis

Suppression définitive : entité et données retirées de `.storage`.

#### Archiver un colis

Lorsqu'un colis est livré, il peut être archivé :

* il sort des capteurs globaux actifs (`sensor.parcels_active`, etc.) et n'est plus interrogé par le coordinator ;
* son entité est **conservée mais désactivée** dans le registre HA (pas supprimée) ;
* ses données restent consultables via le [service d'historique](#services-home-assistant).

---

## Providers

### MVP : La Poste seul

Un seul provider est implémenté au MVP : **La Poste**, qui couvre Colissimo, Chronopost et le courrier suivi.

```text
Provider La Poste
    ├── Colissimo
    ├── Chronopost
    └── Lettre suivie
```

Support :

* Statut courant
* Historique des événements
* Localisation (si disponible)

Les autres transporteurs (UPS, DHL, Mondial Relay, FedEx, GLS, DPD, Amazon Logistics…) sont hors MVP. L'architecture provider (voir plus bas) reste conçue pour les accueillir sans refonte — l'ordre de priorité recommandé pour la suite est celui de `FRANCE-API.md` (Mondial Relay, UPS, DHL en priorité V2).

### Détection automatique — reportée

Avec un seul provider, il n'y a rien à détecter : tout colis ajouté est traité comme La Poste. Le champ `carrier` est conservé dans le modèle de données pour ne pas casser la compatibilité quand un second provider sera ajouté, mais l'UI d'ajout n'a pas besoin de proposer de sélection ou d'afficher un score de confiance au MVP.

La détection automatique multi-transporteurs (liste des 10 transporteurs de la vision initiale) redevient pertinente dès l'ajout d'un deuxième provider, en V2.

### Authentification auprès du provider

L'API Suivi de La Poste nécessite une clé développeur. Chaque utilisateur crée son propre compte (gratuit) et saisit sa clé lors de la configuration de l'intégration :

```text
config_flow
    │
    ▼
Saisie de la clé API La Poste
    │
    ▼
Validation (appel de test)
    │
    ▼
Création de la config entry
```

Aucune clé n'est fournie ou partagée par le projet — cohérent avec « sans cloud propriétaire » : pas de quota mutualisé entre utilisateurs, pas de dépendance à un service tiers géré par le projet.

---

## Modèle Home Assistant

### Une config entry, des colis dynamiques

Il n'existe **qu'une seule config entry** par installation, créée une fois via `config_flow` (elle ne porte que la clé API La Poste). Les colis eux-mêmes sont ajoutés et retirés **dynamiquement**, sans repasser par un flow de configuration :

```text
config_flow (une fois)
    │
    ▼
Clé API La Poste

────────────────────────────

parcel_tracker.add (autant de fois que nécessaire)
    │
    ▼
Nouveau colis suivi par le coordinator existant
```

Un unique `DataUpdateCoordinator` gère la liste complète des colis actifs et crée/retire les entités correspondantes au fil de l'eau.

### Identité de l'entité

Le `unique_id` d'un colis est un **UUID interne généré à la création**, indépendant du numéro de suivi. Modifier le tracking number, le nom ou les notes ne change jamais le `unique_id` : l'`entity_id`, l'historique HA, les statistiques et les automatisations existantes restent valides après une modification.

```text
{
  "id": "5e1b1e3a-...-uuid",   # unique_id, stable
  "tracking_number": "...",     # modifiable
  "carrier": "laposte",
  "name": "Commande Amazon",
  "notes": "...",
  "archived": false
}
```

### Rafraîchissement

Un **intervalle fixe unique** pour tous les colis actifs, conforme au cycle documenté ci-dessous — pas de fréquence adaptative par statut au MVP (cette logique, décrite dans `SPECS-API.md`, est reportée à l'éventuelle API mutualisée en V3, où l'économie d'appels a plus d'intérêt à grande échelle).

```text
Toutes les X minutes
      │
      ▼
Liste des colis actifs (non archivés)
      │
      ▼
Interrogation du provider La Poste
      │
      ▼
Comparaison avec l'état précédent
      │
      ▼
Mise à jour des entités
      │
      ▼
Déclenchement des événements Home Assistant
```

---

## Suivi des colis

### Statut actuel

États supportés :

* Créé
* Pris en charge
* En transit
* Arrivé au centre de tri
* En livraison
* Livré
* Retard
* Incident
* Retour expéditeur

### Historique

Chaque événement comprend :

* Date
* Heure
* Libellé
* Localisation (si disponible)

### Informations complémentaires

Selon les informations disponibles :

* Date estimée de livraison
* Dernière localisation
* Dernière mise à jour
* Lien officiel de suivi

---

## Notifications et automatisations

Le composant **n'envoie aucune notification lui-même** au MVP. Il expose :

* des **entités** dont l'état change avec le statut du colis ;
* des **événements** Home Assistant à chaque transition significative.

C'est à l'utilisateur de construire ses propres automatisations (notification mobile, TTS, éclairage, etc.) à partir de ces événements et entités — c'est l'usage idiomatique des intégrations HA (elles exposent des données, elles ne décident pas comment réagir). Les exemples suivants illustrent ce que l'utilisateur peut construire, pas une fonctionnalité livrée :

```text
📦 Votre colis Amazon est en livraison.
📦 Votre colis La Poste vient d'être livré.
```

Déclencheurs disponibles via les événements (voir [Événements](#événements-home-assistant)) :

* Colis ajouté
* Colis mis à jour
* Colis en transit
* Colis en livraison
* Colis livré
* Retard détecté
* Incident détecté

---

## Entités Home Assistant

Chaque colis actif crée une entité, par exemple :

```text
sensor.amazon_order
```

État :

```text
En livraison
```

Attributs :

* `tracking_number`
* `carrier`
* `history`
* `estimated_delivery`
* `last_update`
* `last_location`
* `days_since_shipping`
* `tracking_url`

Un colis archivé conserve son entité (désactivée) — elle n'apparaît plus dans les capteurs globaux ni dans les dashboards par défaut, mais reste consultable si réactivée manuellement.

### Capteurs globaux

* `sensor.parcels_active`
* `sensor.parcels_delivered`
* `sensor.parcels_waiting`
* `sensor.parcels_today`
* `sensor.parcels_late`

Ces capteurs ne comptent que les colis **non archivés**.

---

## Interface de gestion

En plus des services, un menu accessible via **Paramètres → Appareils et services → Parcel Tracker → Configurer** (options flow) permet d'ajouter, modifier, archiver ou supprimer un colis sans passer par Outils de développement ou une automatisation. Les deux surfaces appellent le même coordinator et respectent la même identité d'entité (voir [Identité de l'entité](#identité-de-lentité)).

## Services Home Assistant

* `parcel_tracker.add`
* `parcel_tracker.update` — modifie le nom, les notes et/ou le numéro de suivi d'un colis existant sans recréer son entité
* `parcel_tracker.remove`
* `parcel_tracker.refresh`
* `parcel_tracker.archive`
* `parcel_tracker.get_history` — retourne l'historique des colis (actifs et archivés), filtrable par mois, année et transporteur. C'est la voie d'accès principale pour consulter les colis archivés et implémenter les filtres, puisque le registre d'entités HA n'est pas fait pour ce type de requête.

---

## Événements Home Assistant

* `parcel_added`
* `parcel_updated`
* `parcel_delivered`
* `parcel_removed`
* `parcel_error`

---

## Stockage local

Les données sont enregistrées dans :

```text
.storage/parcel_tracker
```

Exemple :

```json
[
  {
    "id": "5e1b1e3a-...-uuid",
    "tracking_number": "...",
    "carrier": "laposte",
    "name": "Commande Amazon",
    "notes": "",
    "status": "IN_TRANSIT",
    "history": [],
    "archived": false,
    "created_at": "2026-07-01T10:00:00Z"
  }
]
```

---

## Architecture technique

```text
custom_components/
└── parcel_tracker/
    ├── __init__.py
    ├── manifest.json
    ├── config_flow.py       # configuration de la clé API La Poste (une fois)
    ├── coordinator.py       # DataUpdateCoordinator unique, intervalle fixe
    ├── api.py                # client API La Poste
    ├── parcel.py             # modèle de données d'un colis (id, tracking_number, carrier, ...)
    ├── storage.py             # persistance .storage/parcel_tracker
    ├── services.py            # add / remove / refresh / archive / get_history
    ├── sensor.py               # entités colis + capteurs globaux
    ├── translations/
    └── icons.json
```

---

## Architecture des fournisseurs

Le backend reste indépendant du fournisseur de suivi, même si un seul est implémenté au MVP, afin de ne pas devoir réécrire le coordinator/storage à l'ajout d'un second provider.

```python
class TrackingProvider:

    def detect(self, tracking_number):
        pass

    def track(self, tracking_number):
        pass
```

```text
TrackingProvider
    └── La Poste (MVP)
    └── Mondial Relay (V2)
    └── UPS (V2)
    └── DHL (V2)
    └── ...
```

---

## Roadmap

### MVP

* Gestion des colis (ajout, modification, suppression, archivage)
* Provider La Poste (Colissimo, Chronopost, lettre suivie)
* Suivi des colis (statut, historique)
* Entités et capteurs globaux Home Assistant
* Services Home Assistant (`add`, `remove`, `refresh`, `archive`, `get_history`)
* Événements Home Assistant
* Stockage local `.storage`

### V2

* Providers supplémentaires : Mondial Relay, UPS, DHL (priorité selon `FRANCE-API.md`), puis FedEx, GLS, DPD
* Détection automatique du transporteur (redevient pertinente avec plusieurs providers)
* Statistiques (nombre de colis, temps moyen de livraison, répartition par transporteur)
* Gestion des expéditions (réception vs expédition)
* Étiquettes et catégories

### V3

* API REST mutualisée, multi-clients (`parcel-tracker-api` — voir `SPECS-API.md`, `VEILLE-API.md`) : authentification par clé API, cache, fréquence de rafraîchissement adaptative par statut
* Extension navigateur (détection sur page transporteur/Amazon)
* Partage Android / iOS
* Scan de QR Code
* API publique communautaire

---

## Principes techniques

* Distribution via HACS
* Fonctionnement sans cloud propriétaire — clés API fournies par l'utilisateur, aucune dépendance à un service géré par le projet
* Architecture extensible basée sur des fournisseurs ("providers"), même à un seul provider au MVP
* Stockage local dans `.storage`
* Un seul `DataUpdateCoordinator`, intervalle de rafraîchissement fixe
* `unique_id` des entités colis basé sur un identifiant interne stable, jamais sur le numéro de suivi
* Pas de notification native : l'intégration expose des entités et événements, l'utilisateur construit ses automatisations
* API interne basée sur les services et événements Home Assistant
* Compatibilité avec les automatisations, tableaux de bord et assistants vocaux
