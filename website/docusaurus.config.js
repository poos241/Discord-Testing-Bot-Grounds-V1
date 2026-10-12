// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Bot Developer Handbook',
  tagline: 'How the Discord bot is built — architecture, patterns, and examples',
  url: 'https://poos241.github.io',
  baseUrl: '/Discord-Testing-Bot-Grounds-V1/',
  organizationName: 'poos241',
  projectName: 'Discord-Testing-Bot-Grounds-V1',
  onBrokenLinks: 'throw',
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          editUrl:
            'https://github.com/poos241/Discord-Testing-Bot-Grounds-V1/edit/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],
  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      navbar: {
        title: 'Bot Developer Handbook',
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            href: 'https://github.com/poos241/Discord-Testing-Bot-Grounds-V1',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      colorMode: {
        defaultMode: 'dark',
        respectPrefersColorScheme: false,
      },
    }),
  themes: ['@easyops-cn/docusaurus-search-local'],
};

module.exports = config;
