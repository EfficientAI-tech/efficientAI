// @ts-check
import { themes as prismThemes } from "prism-react-renderer";

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "EfficientAI Docs",
  tagline: "Multi-cloud AI orchestration made easy",
  favicon: "img/favicon.png",

  markdown: {
    mermaid: true,
  },
  themes: ['@docusaurus/theme-mermaid'],

  url: "https://docs.efficientai.com",
  baseUrl: "/",

  organizationName: "efficientai",
  projectName: "docs",

  onBrokenLinks: "throw",
  onBrokenMarkdownLinks: "warn",

  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          sidebarPath: require.resolve("./sidebars.js"),
          editUrl: "https://github.com/efficientai/docs/tree/main/",
        },
        theme: {
          customCss: require.resolve("./src/css/custom.css"),
        },
      },
    ],
  ],

  themeConfig: {
    image: "img/efficientai-social-card.jpg",
    navbar: {
      title: "Efficient",
      logo: {
        alt: "Efficient AI Logo",
        src: "img/favicon.png",
        href: "/docs/intro",
      },
      items: [
        { to: "/docs/intro", label: "Docs", position: "left" },
        { href: "https://github.com/efficientai/docs", label: "GitHub", position: "right" },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Docs",
          items: [{ label: "Introduction", to: "/docs/intro" }],
        },
        {
          title: "Community",
          items: [{ label: "Discord", href: "https://discord.gg/efficientai" }],
        },
        {
          title: "More",
          items: [
            { label: "GitHub", href: "https://github.com/efficientai/docs" },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Efficient AI.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  },
};

export default config;
