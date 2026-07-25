import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
  title: 'BSSCI Service Center',
  description: 'IoT Device Management System for mioty sensors and base stations',
  srcDir: '.',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }]
  ],
  ignoreDeadLinks: [
    /localhost:\d+/
  ],
  themeConfig: {
    siteTitle: 'BSSCI Service Center',
    nav: [
      { text: 'Guide', link: '/guide/introduction' },
      { text: 'API Reference', link: '/api/reference' },
      { text: 'Deployment', link: '/deployment/docker' },
      { text: 'GitHub', link: 'https://github.com/plasmonized/containerized-mioty-Service-Center' }
    ],
    sidebar: {
      '/guide/': [
        {
          text: 'Getting Started',
          items: [
            { text: 'Introduction', link: '/guide/introduction' },
            { text: 'Installation', link: '/guide/installation' },
            { text: 'Configuration', link: '/guide/configuration' }
          ]
        },
        {
          text: 'Core Features',
          items: [
            { text: 'Sensor Management', link: '/guide/sensor-management' },
            { text: 'Auto-Detach System', link: '/guide/auto-detach' },
            { text: 'MQTT Integration', link: '/guide/mqtt-integration' },
            { text: 'Web Interface', link: '/guide/web-interface' }
          ]
        },
        {
          text: 'Advanced Topics',
          items: [
            { text: 'Variable MAC', link: '/guide/variable-mac' },
            { text: 'OMS/Wireless M-Bus', link: '/guide/oms-wmbus' },
            { text: 'Advanced Features', link: '/guide/advanced-features' },
            { text: 'Troubleshooting', link: '/guide/troubleshooting' }
          ]
        }
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [
            { text: 'API Reference', link: '/api/reference' }
          ]
        }
      ],
      '/deployment/': [
        {
          text: 'Deployment',
          items: [
            { text: 'Docker Deployment', link: '/deployment/docker' },
            { text: 'Updating', link: '/deployment/updating' },
            { text: 'Release Please', link: '/deployment/release-please' }
          ]
        }
      ]
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/plasmonized/containerized-mioty-Service-Center' }
    ],
    footer: {
      copyright: 'Copyright © 2024'
    },
    search: {
      provider: 'local'
    }
  },
  outDir: '../../dist',
  markdown: {
    theme: {
      light: 'github-light',
      dark: 'github-dark'
    },
    diagram: {
      inline: true
    }
  }
}))
