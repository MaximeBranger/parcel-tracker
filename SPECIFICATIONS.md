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
* Transporteur — au choix parmi les providers configurés (voir [Providers](#providers))
* Date d'ajout
* Notes (optionnel)
* Cible de notification (optionnel) — voir [Notifications et automatisations](#notifications-et-automatisations)

#### Modifier un colis

L'utilisateur peut modifier :

* le nom
* les notes
* le numéro de suivi
* le transporteur *(dès qu'un second provider existe)*
* la cible de notification

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

### Providers implémentés

Sept providers sont implémentés : **La Poste** (Colissimo, Chronopost, courrier suivi), **FedEx**, **DHL**, **UPS**, **Mondial Relay**, **PostNord** et **DPD**.

```text
TrackingProvider
    ├── La Poste       (API Suivi, clé API)
    ├── FedEx           (Track API v1, OAuth2 client_credentials)
    ├── DHL              (Unified Tracking API, clé API)
    ├── UPS              (Track API v1, OAuth2 client_credentials)
    ├── Mondial Relay    (webservice WSI2, login + clé privée signée)
    ├── PostNord         (Track & Trace API v5, clé API)
    └── DPD              (GeoService, login + mot de passe pro)
```

Support (variable selon les données exposées par chaque API) :

* Statut courant
* Historique des événements
* Date de livraison estimée (non exposée par Mondial Relay au MVP)
* Localisation (si disponible)

Comme Mondial Relay, DPD n'a pas de portail développeur en libre-service : les identifiants (login + mot de passe) ne sont délivrés qu'aux expéditeurs sous contrat professionnel DPD Group, et le contrat GeoService suivi ici (`providers/dpd.py`) est une reconstitution best-effort à confirmer avec de vrais identifiants, pas une spec vérifiée.

Les autres transporteurs (GLS, Amazon Logistics…) restent hors périmètre. L'architecture provider (voir plus bas) reste conçue pour les accueillir sans refonte.

### Détection automatique — reportée

Chaque colis porte un champ `carrier` explicite, choisi par l'utilisateur à l'ajout (aucune valeur par défaut imposée au-delà de La Poste pour compatibilité ascendante). La détection automatique du transporteur à partir du numéro de suivi (liste des 10 transporteurs de la vision initiale) reste hors périmètre et pourra être ajoutée plus tard sans changer le modèle de données.

### Authentification auprès des providers

Chaque provider nécessite ses propres identifiants développeur, saisis par l'utilisateur lors de la configuration de l'intégration. Tous les transporteurs sont **optionnels** dans le config_flow : l'utilisateur ne renseigne que ceux qu'il utilise réellement, mais au moins un est requis pour créer la config entry.

```text
config_flow
    │
    ▼
Saisie des identifiants (0 à N transporteurs, ≥ 1 requis)
    │
    ▼
Validation (un appel de test par transporteur renseigné)
    │
    ▼
Création de la config entry
```

| Transporteur    | Identifiants requis                              | Schéma d'authentification        |
|-----------------|---------------------------------------------------|-----------------------------------|
| La Poste        | Clé API                                            | Clé API en en-tête                |
| FedEx           | Client ID + Client secret                          | OAuth2 client_credentials         |
| DHL             | Clé API                                            | Clé API en en-tête                |
| UPS             | Client ID + Client secret                          | OAuth2 client_credentials         |
| Mondial Relay   | Login (Enseigne) + Clé privée                      | Hash MD5 signé (webservice WSI2)  |
| PostNord        | Clé API                                            | Clé API en paramètre de requête   |
| DPD             | Login + mot de passe (compte pro DPD Group)        | Token de session (GeoService)     |

Aucune clé n'est fournie ou partagée par le projet — cohérent avec « sans cloud propriétaire » : pas de quota mutualisé entre utilisateurs, pas de dépendance à un service tiers géré par le projet. Les identifiants d'un ou plusieurs transporteurs peuvent être ajoutés ou corrigés après la création de l'intégration via **Reconfigurer** (Paramètres → Appareils et services → Parcel Tracker).

---

## Modèle Home Assistant

### Une config entry, des colis dynamiques

Il n'existe **qu'une seule config entry** par installation, créée une fois via `config_flow` (elle ne porte que les identifiants des providers). Les colis eux-mêmes sont ajoutés et retirés **dynamiquement**, sans repasser par un flow de configuration :

```text
config_flow (une fois)
    │
    ▼
Identifiants des transporteurs configurés

────────────────────────────

parcel_tracker.add (autant de fois que nécessaire)
    │
    ▼
Nouveau colis suivi par le coordinator existant, pour le transporteur choisi
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
Interrogation du provider correspondant au transporteur de chaque colis
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

Le composant expose :

* des **entités** dont l'état change avec le statut du colis ;
* des **événements** Home Assistant à chaque transition significative ;
* une **notification native optionnelle, par colis** : le champ `notify_target` (formulaire d'ajout/modification, options flow uniquement — pas exposé dans les services YAML) permet de choisir une cible parmi les entités du domaine `notify` et les services legacy encore enregistrés sous ce domaine (Home Assistant a fait cohabiter les deux formats lors de sa migration vers les entités `notify`). Quand ce champ est renseigné, le coordinator appelle cette cible (`notify.send_message` pour une entité, `notify.<service>` pour un service legacy) exactement quand il émet `parcel_updated` (même condition : statut ou historique modifié) — jamais sur `parcel_error`, pour ne pas spammer sur une clé API cassée. Le message envoyé est `"{nom du colis} : {dernier libellé d'historique}"`, avec repli sur le statut simplifié traduit si l'historique n'a pas encore de libellé exploitable. Un échec d'envoi (cible supprimée/indisponible) est journalisé (`_LOGGER.warning`) sans jamais interrompre le rafraîchissement des autres colis.

En dehors de ce cas, c'est à l'utilisateur de construire ses propres automatisations (TTS, éclairage, notification vers une autre cible, etc.) à partir des événements et entités — c'est l'usage idiomatique des intégrations HA. Les exemples suivants illustrent ce que l'utilisateur peut construire en plus de la notification native :

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
* `parcel_tracker.get_configured_carriers` — retourne les transporteurs dont les identifiants sont configurés sur cette entrée (`list(coordinator.providers)`). Permet à un frontend (ex. `parcel_tracker-card`) de ne proposer que ces transporteurs dans son propre formulaire d'ajout/modification, sans avoir accès aux données de la config entry — même logique que le scoping déjà fait par `ParcelTrackerOptionsFlow._configured_carriers` pour son propre formulaire.

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
    ├── config_flow.py       # identifiants des providers (0..N, ≥1 requis) + reconfigure
    ├── coordinator.py       # DataUpdateCoordinator unique, intervalle fixe
    ├── providers/            # un client par transporteur
    │   ├── base.py            # interface TrackingProvider + erreurs communes
    │   ├── registry.py         # mapping carrier -> provider, clés de config requises
    │   ├── laposte.py
    │   ├── fedex.py
    │   ├── dhl.py
    │   ├── ups.py
    │   ├── mondial_relay.py
    │   ├── postnord.py
    │   └── dpd.py
    ├── parcel.py             # modèle de données d'un colis (id, tracking_number, carrier, ...)
    ├── storage.py             # persistance .storage/parcel_tracker
    ├── services.py            # add / remove / refresh / archive / get_history
    ├── sensor.py               # entités colis + capteurs globaux
    ├── translations/
    └── icons.json
```

---

## Architecture des fournisseurs

Le backend reste indépendant du fournisseur de suivi : le coordinator interroge un `TrackingProvider` par colis (sélectionné via son champ `carrier`), sans connaître les détails d'authentification ou de format de réponse propres à chaque transporteur.

```python
class TrackingProvider(ABC):

    async def async_validate_credentials(self) -> None:
        ...

    async def async_track(self, tracking_number: str) -> dict:
        ...
```

```text
TrackingProvider
    ├── La Poste
    ├── FedEx
    ├── DHL
    ├── UPS
    ├── Mondial Relay
    ├── PostNord
    ├── DPD
    └── ... (GLS, Amazon Logistics — non implémentés)
```

Un provider n'est instancié que si ses identifiants sont configurés (voir [Authentification](#authentification-auprès-des-providers)) : `providers/registry.py` associe chaque transporteur aux clés de config qu'il attend et à sa classe. Si un colis référence un transporteur dont les identifiants ont été retirés, le coordinator émet un événement `parcel_error` au lieu d'échouer — les autres colis continuent d'être rafraîchis normalement.

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

### V2 (en cours)

* ✅ Providers supplémentaires : FedEx, DHL, UPS, Mondial Relay, PostNord, DPD
* ✅ Sélection du transporteur à l'ajout/modification d'un colis (UI et services)
* ✅ Identifiants par transporteur optionnels et modifiables après coup (`Reconfigurer`)
* Providers restants : GLS
* Détection automatique du transporteur (à partir du format du numéro de suivi)
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
* Architecture extensible basée sur des fournisseurs ("providers"), chacun activé indépendamment selon les identifiants configurés
* Stockage local dans `.storage`
* Un seul `DataUpdateCoordinator`, intervalle de rafraîchissement fixe
* `unique_id` des entités colis basé sur un identifiant interne stable, jamais sur le numéro de suivi
* Notification native optionnelle par colis (`notify_target`), en plus des entités et événements exposés pour les automatisations de l'utilisateur
* API interne basée sur les services et événements Home Assistant
* Compatibilité avec les automatisations, tableaux de bord et assistants vocaux
