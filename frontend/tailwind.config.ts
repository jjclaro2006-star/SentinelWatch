import type { Config } from 'tailwindcss'

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'var(--border)',
        background: 'var(--bg-base)',
        foreground: 'var(--text-pri)',
        muted: {
          DEFAULT: 'var(--bg-elevated)',
          foreground: 'var(--text-muted)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          foreground: 'var(--text-pri)',
        },
        destructive: {
          DEFAULT: 'var(--sev-alta)',
          foreground: '#ffffff',
        },
        card: {
          DEFAULT: 'var(--bg-surface)',
          foreground: 'var(--text-pri)',
        },
        popover: {
          DEFAULT: 'var(--bg-elevated)',
          foreground: 'var(--text-pri)',
        },
        secondary: {
          DEFAULT: 'var(--bg-elevated)',
          foreground: 'var(--text-sec)',
        },
        input: 'var(--border)',
        ring: 'var(--accent)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Cascadia Code', 'monospace'],
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
} satisfies Config
