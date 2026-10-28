/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'intro',
    {
      type: 'category',
      label: 'Fundamentals',
      items: ['project-map', 'boot-sequence', 'cogs', 'views-buttons', 'permissions', 'config-helpers'],
    },
    {
      type: 'category',
      label: 'Data',
      items: ['data-layer', 'adding-a-table'],
    },
    {
      type: 'category',
      label: 'Systems',
      items: ['level-system', 'eat-it-or-yeet-it', 'adding-a-food-source', 'watch-list', 'logger', 'building-mode-batch'],
    },
    {
      type: 'category',
      label: 'Guides',
      items: ['recipes', 'testing', 'checklist'],
    },
  ],
};

module.exports = sidebars;
