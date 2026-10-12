/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'intro',
    {
      type: 'category',
      label: 'Fundamentals',
      items: ['project-map', 'boot-sequence', 'cogs', 'permissions', 'config-helpers'],
    },
    {
      type: 'category',
      label: 'Data',
      items: ['data-layer'],
    },
    {
      type: 'category',
      label: 'Systems',
      items: ['level-system', 'eat-it-or-yeet-it'],
    },
    {
      type: 'category',
      label: 'Guides',
      items: ['recipes', 'testing', 'checklist'],
    },
  ],
};

module.exports = sidebars;
