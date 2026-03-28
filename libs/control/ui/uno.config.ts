import { defineConfig, presetMini, presetWind3 } from 'unocss';

export default defineConfig({
  presets: [presetMini(), presetWind3()],
  shortcuts: {
    'flex-center': 'flex items-center justify-center',
    'control-card': 'rd-18px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] shadow-[var(--control-shadow)]',
    'control-muted-card':
      'rd-18px border border-solid border-[var(--control-border)] bg-[var(--control-panel-muted)] shadow-[var(--control-shadow)]',
  },
  theme: {
    colors: {
      'control-bg': 'var(--control-bg)',
      'control-panel': 'var(--control-panel)',
      'control-panel-muted': 'var(--control-panel-muted)',
      'control-border': 'var(--control-border)',
      'control-text': 'var(--control-text)',
      'control-subtle': 'var(--control-subtle)',
      'control-primary': 'var(--control-primary)',
      'control-primary-soft': 'var(--control-primary-soft)',
      'control-accent': 'var(--control-accent)',
      'control-success': 'var(--control-success)',
      'control-warning': 'var(--control-warning)',
      'control-danger': 'var(--control-danger)',
    },
  },
});

