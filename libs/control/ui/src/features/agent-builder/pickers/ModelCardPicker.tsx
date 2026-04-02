import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Input, Message, Spin, Typography } from '@arco-design/web-react';
import { Brain, CloudStorage } from '@icon-park/react';
import { controlClient } from '@/shared/api/controlClient';
import type { ModelConfigDTO } from '@/shared/types/api';

type ModelCardPickerProps = {
  value?: string;
  onChange?: (value: string) => void;
};

const PAGE_SIZE = 24;
const ACCENT = '#00f0ff';
const GLOW = 'rgba(0,240,255,0.20)';
const TINT = 'rgba(0,240,255,0.06)';

export default function ModelCardPicker(props: ModelCardPickerProps) {
  const [models, setModels] = useState<ModelConfigDTO[]>([]);
  const [loadedPage, setLoadedPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [hasActivated, setHasActivated] = useState(false);
  const loadingRef = useRef(false);

  const loadPage = useCallback(async (pageNumber: number) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const page = await controlClient.models.list({ pageSize: PAGE_SIZE, pageNumber });
      const items = page.models ?? [];
      setModels((prev) => {
        const existing = new Set(prev.map((m) => m.name));
        const newItems = items.filter((m) => m.name && !existing.has(m.name));
        return [...prev, ...newItems];
      });
      setLoadedPage(pageNumber);
      const totalPages = page.total_pages ?? (page.total_size ? Math.ceil(page.total_size / PAGE_SIZE) : undefined);
      setHasMore(totalPages !== undefined ? pageNumber < totalPages : items.length >= PAGE_SIZE);
    } catch (error) {
      Message.error(error instanceof Error ? error.message : 'Failed to load models');
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hasActivated) {
      setHasActivated(true);
      void loadPage(1);
    }
  }, [hasActivated, loadPage]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return models;
    return models.filter(
      (m) =>
        m.name?.toLowerCase().includes(term) ||
        m.provider?.toLowerCase().includes(term) ||
        m.model?.toLowerCase().includes(term),
    );
  }, [models, search]);

  const handleScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      if (!hasMore || loading) return;
      const el = e.currentTarget;
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
        void loadPage(loadedPage + 1);
      }
    },
    [hasMore, loading, loadPage, loadedPage],
  );

  return (
    <div>
      <Input
        allowClear
        placeholder='Search models...'
        value={search}
        onChange={setSearch}
        className='mb-14px'
      />
      <div
        className='control-scroll grid max-h-360px grid-cols-1 gap-10px overflow-y-auto sm:grid-cols-2 lg:grid-cols-3'
        onScroll={handleScroll}
      >
        {filtered.map((model) => {
          const name = model.name ?? '';
          const isSelected = props.value === name;
          return (
            <div
              key={name}
              className={`builder-card-item ${isSelected ? 'builder-card-item--selected' : ''}`}
              style={{
                '--picker-accent': ACCENT,
                '--picker-glow': GLOW,
              } as React.CSSProperties}
              onClick={() => props.onChange?.(isSelected ? '' : name)}
            >
              {/* Selected check */}
              <div
                className='builder-card-item-check'
                style={{ background: ACCENT, color: '#000' }}
              >
                ✓
              </div>
              <div className='flex items-center gap-8px mb-4px'>
                <div
                  className='builder-card-item-icon'
                  style={{ background: TINT }}
                >
                  <Brain size={16} fill={[ACCENT]} />
                </div>
                <Typography.Text className='block truncate text-13px font-medium text-[var(--control-text)]'>
                  {name}
                </Typography.Text>
              </div>
              <Typography.Text className='block text-11px text-[var(--control-subtle)]'>
                {[model.provider, model.model].filter(Boolean).join(' / ') || 'no provider info'}
              </Typography.Text>
              {model.provider ? (
                <div className='mt-6px flex gap-4px'>
                  <span className='registry-stat-pill' style={{ color: ACCENT, fontSize: '10px', padding: '1px 6px' }}>
                    <CloudStorage size={10} fill={[ACCENT]} />
                    <span className='text-[var(--control-subtle)]'>{model.provider}</span>
                  </span>
                </div>
              ) : null}
            </div>
          );
        })}
        {loading && (
          <div className='col-span-full flex-center py-16px'>
            <Spin size={20} />
          </div>
        )}
        {!loading && filtered.length === 0 && (
          <div className='col-span-full py-16px text-center'>
            <Typography.Text className='text-13px text-[var(--control-subtle)]'>
              No models found
            </Typography.Text>
          </div>
        )}
      </div>
      {hasMore && !loading && (
        <Typography.Text className='mt-8px block text-center text-11px text-[var(--control-subtle)]'>
          Scroll to load more
        </Typography.Text>
      )}
    </div>
  );
}
