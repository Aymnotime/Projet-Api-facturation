# FacturEasy Frontend

Dashboard Next.js pour la plateforme de facturation électronique FacturEasy.

## 🚀 Fonctionnalités

- **Tableau de bord** : Vue d'ensemble avec statistiques et factures récentes
- **Gestion des factures** : Liste, filtrage, pagination, actions (émettre, annuler, payer)
- **Gestion des clients** : Grille de clients avec informations détaillées
- **Paramètres** : Configuration de l'organisation
- **Design responsive** : Interface moderne avec Tailwind CSS
- **Navigation latérale** : Menu de navigation fixe

## 🛠️ Technologies

- **Next.js 15** : Framework React avec App Router
- **TypeScript** : Typage statique
- **Tailwind CSS** : Styles utilitaires
- **Lucide React** : Icônes modernes
- **Axios** : Client HTTP
- **date-fns** : Manipulation de dates
- **clsx + tailwind-merge** : Gestion des classes CSS

## 📁 Structure

```
frontend/
├── app/
│   ├── layout.tsx          # Layout principal
│   ├── page.tsx            # Page principale (dashboard)
│   └── globals.css         # Styles globaux
├── src/
│   ├── components/
│   │   ├── Sidebar.tsx           # Navigation latérale
│   │   ├── DashboardPage.tsx     # Tableau de bord
│   │   ├── InvoicesPage.tsx      # Page des factures
│   │   ├── InvoiceRow.tsx        # Ligne de facture
│   │   ├── CustomersPage.tsx     # Page des clients
│   │   └── SettingsPage.tsx      # Page des paramètres
│   ├── lib/
│   │   ├── api.ts                # Client API
│   │   └── utils.ts              # Utilitaires
│   └── types/
│       └── index.ts              # Types TypeScript
└── package.json
```

## 🔧 Installation

```bash
npm install
```

## 🏃 Démarrage

```bash
# Développement
npm run dev

# Build production
npm run build

# Start production
npm start
```

## 🔗 Variables d'environnement

Créez un fichier `.env.local` :

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

## 📊 Pages implémentées

### Tableau de Bord (`/`)
- Statistiques clés (revenu, factures, clients)
- Liste des 5 dernières factures
- Cartes métriques colorées

### Factures (`/invoices`)
- Liste paginée avec filtrage par statut
- Recherche par numéro
- Actions : émettre, annuler, marquer comme payée
- Détail extensible des lignes de facture
- Pagination complète

### Clients (`/customers`)
- Grille responsive de clients
- Informations complètes (adresse, TVA, contact)
- Pagination
- Boutons d'action rapides

### Paramètres (`/settings`)
- Formulaire de configuration organisation
- Champs : nom, raison sociale, TVA, adresse
- Sélecteur de pays européen

## 🎨 Composants

- **Sidebar** : Navigation fixe avec liens vers les pages
- **InvoiceRow** : Ligne de tableau extensible pour les factures
- **Pages** : Composants autonomes pour chaque section

## 🔌 Intégration API

Le client API (`src/lib/api.ts`) gère :
- Authentification Bearer token
- Requêtes vers le backend FastAPI
- Gestion des erreurs
- Types TypeScript pour la sécurité

Endpoints supportés :
- `GET /invoices` - Liste des factures
- `GET /invoices/:id` - Détail facture
- `POST /invoices/:id/issue` - Émettre facture
- `POST /invoices/:id/cancel` - Annuler facture
- `POST /invoices/:id/mark-paid` - Marquer payée
- `GET /customers` - Liste des clients
- `PATCH /organizations/:id` - Mise à jour organisation

## 🚧 À implémenter

- [ ] Création/édition de factures (modal ou page dédiée)
- [ ] Création/édition de clients
- [ ] Téléchargement PDF des factures
- [ ] Visualisation PDF inline
- [ ] Authentification complète (login/logout)
- [ ] Gestion des clés API
- [ ] Webhooks et notifications
- [ ] Export CSV/Excel
- [ ] Graphiques et analytics avancés

## 📝 Notes

- Le frontend suppose que le backend est démarré sur `http://localhost:8000`
- Les tokens d'authentification sont stockés dans `localStorage`
- Le design est optimisé pour desktop et tablette

## 📄 Licence

MIT
