import React from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

const sections = [
  {
    title: 'Fundamentals',
    desc: 'Project map, boot sequence, cogs, permissions, and config helpers.',
    to: '/docs/project-map',
  },
  {
    title: 'Data layer',
    desc: 'SQLite storage helpers and JSON files — which to use and when.',
    to: '/docs/data-layer',
  },
  {
    title: 'Systems',
    desc: 'How the level system and Eat It or Yeet It work internally.',
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
      title="Bot Developer Handbook"
      description="How the Discord bot is built — architecture, patterns, and examples."
    >
      <header className="hero hero--primary">
        <div className="container">
          <Heading as="h1" className="hero__title">
            Bot Developer Handbook
          </Heading>
          <p className="hero__subtitle">
            How the Discord bot is built — architecture, patterns, and examples.
          </p>
          <div>
            <Link className="button button--secondary button--lg" to="/docs/intro">
              Start reading
            </Link>
          </div>
        </div>
      </header>
      <main className="container" style={{ padding: '2rem 0' }}>
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
