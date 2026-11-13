import React from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

// Feature cards, Vercel-docs style: emoji icon + title + one line.
// Each links to the doc page that covers that system.
const features = [
  {
    icon: '🛡️',
    title: 'Moderation',
    desc: 'Timeouts, bans, kicks, mod cases, and the GitHub ban log — with a mini mod panel on every user card.',
    to: '/docs/commands',
    accent: 'feature-card--pink',
  },
  {
    icon: '📈',
    title: 'Levels & XP',
    desc: 'Message XP, rank cards, daily streaks, role rewards, and XP events — off by default, per guild.',
    to: '/docs/level-system',
    accent: 'feature-card--purple',
  },
  {
    icon: '🎮',
    title: 'Eat It or Yeet It',
    desc: 'The party game: vote on foods, earn points, run it back. Live meals from TheMealDB plus a community pool.',
    to: '/docs/eat-it-or-yeet-it',
    accent: 'feature-card--gold',
  },
  {
    icon: '📜',
    title: 'Logger',
    desc: 'Server-wide event logging to dedicated channels — messages, members, voice, server, and moderation.',
    to: '/docs/logger',
    accent: 'feature-card--blue',
  },
  {
    icon: '👀',
    title: 'Watch List',
    desc: 'Put users on a per-server watch list and mirror their messages to a mod log channel.',
    to: '/docs/watch-list',
    accent: 'feature-card--mint',
  },
  {
    icon: '🔐',
    title: 'Custom permissions',
    desc: 'Grant a set of commands to a role or a user — a per-command allow list that replaces the Discord check.',
    to: '/docs/permissions',
    accent: 'feature-card--rose',
  },
];

// Doc-section cards.
const sections = [
  {
    title: 'Two bots',
    desc: 'How Havenly Bot 2.0 and Havenly Helper split the work — same codebase, shared Postgres, one bridge hub.',
    to: '/docs/two-bots',
  },
  {
    title: 'Fundamentals',
    desc: 'Project map, boot sequence, cogs, commands, views & buttons, permissions, and config helpers.',
    to: '/docs/project-map',
  },
  {
    title: 'Data layer',
    desc: 'Postgres storage helpers and tables — which to use and when, plus adding tables and columns.',
    to: '/docs/data-layer',
  },
  {
    title: 'Systems',
    desc: 'How the level system, Eat It or Yeet It, Watch List, Logger, and bot settings work internally.',
    to: '/docs/level-system',
  },
  {
    title: 'Guides',
    desc: 'Copy-paste recipes, testing, and the new-feature checklist.',
    to: '/docs/recipes',
  },
];

export default function Home() {
  return (
    <Layout
      title="Havenly Bot 2.0 & Havenly Helper Handbook"
      description="How Havenly Bot 2.0 and Havenly Helper are built — architecture, patterns, and examples."
    >
      <header className="hero hero--primary">
        <div className="container">
          <Heading as="h1" className="hero__title">
            Havenly Bot 2.0 &amp; Havenly Helper
          </Heading>
          <p className="hero__subtitle">
            Two bots, one codebase: the main bot runs the day-to-day, and the
            Helper runs setup and background jobs — both sharing one Postgres
            database.
          </p>
          <div>
            <Link className="button button--secondary button--lg" to="/docs/intro">
              Start reading
            </Link>
            <Link
              className="button button--primary button--lg"
              to="/docs/two-bots"
              style={{ marginLeft: '0.75rem' }}
            >
              How the two bots split the work
            </Link>
          </div>
        </div>
      </header>
      <main className="container" style={{ padding: '2rem 0' }}>
        <div className="two-bot-strip">
          <div className="two-bot-chip two-bot-chip--main">
            <h3>🤍 Havenly Bot 2.0 — the main bot</h3>
            <p>
              The face of the pair. It runs the in-the-moment commands:
              moderation, user info, levels, games, QOTD, and everything
              members and mods use day to day. 54 top-level commands.
            </p>
          </div>
          <div className="two-bot-chip two-bot-chip--helper">
            <h3>⭐ Havenly Helper — the worker bot</h3>
            <p>
              The behind-the-scenes bot. It runs setup and config, batch
              jobs (scans, backfills, backups), and the timeout board.
              11 top-level commands — and no command is on both bots.
            </p>
          </div>
        </div>

        <h2 className="home-section-title">🔧 Core Features</h2>
        <p className="home-section-sub">
          What the two bots do, and where each system lives.
        </p>
        <div className="row">
          {features.map((f) => (
            <div className="col col--4" key={f.to + f.title} style={{ marginBottom: '1rem' }}>
              <div className={`card feature-card ${f.accent}`}>
                <div className="card__header">
                  <div className="feature-card__icon">{f.icon}</div>
                  <h3>{f.title}</h3>
                </div>
                <div className="card__body">
                  <p>{f.desc}</p>
                </div>
                <div className="card__footer">
                  <Link className="button button--primary button--block" to={f.to}>
                    Open
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>

        <h2 className="home-section-title">📚 Docs</h2>
        <p className="home-section-sub">
          The how-it-works companion to the README — architecture, patterns,
          and copy-paste examples.
        </p>
        <div className="row">
          {sections.map((s) => (
            <div className="col col--6" key={s.to} style={{ marginBottom: '1rem' }}>
              <div className="card">
                <div className="card__header">
                  <h3>{s.title}</h3>
                </div>
                <div className="card__body">
                  <p>{s.desc}</p>
                </div>
                <div className="card__footer">
                  <Link className="button button--primary button--block" to={s.to}>
                    Open
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
    </Layout>
  );
}
