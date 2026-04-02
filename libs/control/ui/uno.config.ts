import { defineConfig, presetMini, presetWind3 } from 'unocss';

export default defineConfig({
  presets: [presetMini(), presetWind3()],
  shortcuts: {
    'flex-center': 'flex items-center justify-center',
    'control-card': 'rd-18px border border-solid border-[var(--control-border)] bg-[var(--control-panel)] shadow-[var(--control-shadow)]',
    'control-muted-card':
      'rd-18px border border-solid border-[var(--control-border)] bg-[var(--control-panel-muted)] shadow-[var(--control-shadow)]',
    'control-glow-hover': 'hover:shadow-[var(--control-glow)] hover:border-[rgba(0,240,255,0.25)] transition-all duration-200',
    'builder-card-selected': 'border-[var(--control-primary)] shadow-[var(--control-glow)]',
    'registry-card-icon': 'w-40px h-40px rd-10px flex-center shrink-0',
    'registry-stat-pill': 'flex items-center gap-4px rd-full px-8px py-2px text-12px font-mono border border-solid border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)]',
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

