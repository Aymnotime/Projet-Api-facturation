"use client";

import { useEffect, useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [status, setStatus] = useState("Connexion...");

  useEffect(() => {
    fetch(`${apiUrl}/health`)
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then(() => setStatus("API opérationnelle"))
      .catch(() => setStatus("API indisponible"));
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">F</span><span>Facturation</span></div>
        <nav><a className="active" href="#overview">Vue générale</a><a href="#invoices">Factures</a><a href="#customers">Clients</a><a href="#events">Événements</a></nav>
        <div className="environment"><span className="dot" />Environnement test</div>
      </aside>
      <section className="content">
        <header className="topbar"><div><p className="eyebrow">Console API</p><h1>Bonjour, votre activité en un regard.</h1></div><button className="profile">AC</button></header>
        <div className="status"><span className="dot" />{status}<span className="status-detail">Dernière vérification à l’instant</span></div>
        <section className="metrics" aria-label="Indicateurs">
          <article><span>Factures ce mois</span><strong>0</strong><small>Prêt à recevoir vos premières données</small></article>
          <article><span>Montant traité</span><strong>0,00 €</strong><small>Aucune facture émise</small></article>
          <article><span>Appels API</span><strong>0</strong><small>Environnement test</small></article>
        </section>
        <section className="lower" id="overview"><div className="panel"><div className="panel-heading"><div><p className="eyebrow">Démarrage</p><h2>Construisez votre premier flux</h2></div><span className="step-count">01 / 03</span></div><p>Créez une organisation, générez une clé API, puis envoyez votre première facture depuis votre logiciel.</p><div className="progress"><span /></div><button className="primary">Créer une clé API <span>→</span></button></div><div className="panel activity"><div className="panel-heading"><div><p className="eyebrow">Système</p><h2>État des services</h2></div></div><div className="service"><span className="service-icon">API</span><div><strong>API publique</strong><small>Réponse en temps réel</small></div><b>Opérationnel</b></div><div className="service"><span className="service-icon">DB</span><div><strong>Base de données</strong><small>Stockage sécurisé</small></div><b>Opérationnel</b></div></div></section>
      </section>
    </main>
  );
}
