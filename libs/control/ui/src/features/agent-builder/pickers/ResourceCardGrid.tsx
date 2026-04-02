import { useCallback, useEffect, useRef, useState } from 'react';
import { Input, Message, Spin, Typography } from '@arco-design/web-react';
import { REGISTRY_ICONS } from '@/pages/registry/registryIcons';
import type { NumberPageMeta } from '@/shared/types/api';

type NamedResource = {
  name?: string;
  description?: string;
};

type ResourceCardGridProps<TPage extends NumberPageMeta> = {
  label: string;
  value?: string | string[];
  onChange?: (value: string | string[]) => void;
  fetchPage: (params: { pageSize: number; pageNumber: number }) => Promise<TPage>;
  extractItems: (page: TPage) => NamedResource[];
  mode?: 'single' | 'multiple';
  pageSize?: number;
  accent?: string;
  iconKey?: keyof typeof REGISTRY_ICONS;
};

const DEFAULT_PAGE_SIZE = 24;

export default function ResourceCardGrid<TPage extends NumberPageMeta>(
  props: ResourceCardGridProps<TPage>,
) {
  const pageSize = props.pageSize ?? DEFAULT_PAGE_SIZE;
  const mode = props.mode ?? 'multiple';
  const accent = props.accent ?? '#00f0ff';
  const glow = accent + '33'; // ~20% opacity hex
  const tint = accent + '0f'; // ~6% opacity hex
  const IconComp = props.iconKey ? REGISTRY_ICONS[props.iconKey] : null;

  const [items, setItems] = useState<NamedResource[]>([]);
  const [loadedPage, setLoadedPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [hasActivated, setHasActivated] = useState(false);
  const loadingRef = useRef(false);

  const selectedSet = new Set(
    Array.isArray(props.value) ? props.value : props.value ? [props.value] : [],
  );

  const loadPage = useCallback(
    async (pageNumber: number) => {
      if (loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      try {
        const page = await props.fetchPage({ pageSize, pageNumber });
        const pageItems = props.extractItems(page);
        setItems((prev) => {
          const existing = new Set(prev.map((i) => i.name));
          const newItems = pageItems.filter((i) => i.name && !existing.has(i.name));
          return [...prev, ...newItems];
        });
        setLoadedPage(pageNumber);
        const totalPages =
          page.total_pages ?? (page.total_size ? Math.ceil(page.total_size / pageSize) : undefined);
        setHasMore(
          totalPages !== undefined ? pageNumber < totalPages : pageItems.length >= pageSize,
        );
      } catch (error) {
        Message.error(error instanceof Error ? error.message : `Failed to load ${props.label}`);
      } finally {
        loadingRef.current = false;
        setLoading(false);
      }
    },
    [pageSize, props],
  );

  useEffect(() => {
    if (!hasActivated) {
      setHasActivated(true);
      void loadPage(1);
    }
  }, [hasActivated, loadPage]);

  const filtered = search.trim()
    ? items.filter((i) => i.name?.toLowerCase().includes(search.trim().toLowerCase()))
    : items;

  function toggleItem(name: string) {
    if (mode === 'single') {
      const current = Array.isArray(props.value) ? props.value[0] : props.value;
      props.onChange?.(current === name ? '' : name);
      return;
    }
    const current = new Set(selectedSet);
    if (current.has(name)) {
      current.delete(name);
    } else {
      current.add(name);
    }
    props.onChange?.(Array.from(current));
  }

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
        placeholder={`Search ${props.label}...`}
        value={search}
        onChange={setSearch}
        className='mb-14px'
      />
      <div
        className='control-scroll grid max-h-300px grid-cols-1 gap-10px overflow-y-auto sm:grid-cols-2 lg:grid-cols-3'
        onScroll={handleScroll}
      >
        {filtered.map((item) => {
          const name = item.name ?? '';
          const isSelected = selectedSet.has(name);
          return (
            <div
              key={name}
              className={`builder-card-item ${isSelected ? 'builder-card-item--selected' : ''}`}
              style={{
                '--picker-accent': accent,
                '--picker-glow': glow,
              } as React.CSSProperties}
              onClick={() => toggleItem(name)}
            >
              {/* Selected check */}
              <div
                className='builder-card-item-check'
                style={{ background: accent, color: '#000' }}
              >
                ✓
              </div>
              <div className='flex items-center gap-8px mb-4px'>
                {IconComp ? (
                  <div
                    className='builder-card-item-icon'
                    style={{ background: tint }}
                  >
                    <IconComp size={16} fill={[accent]} />
                  </div>
                ) : null}
                <Typography.Text className='block truncate text-13px font-medium text-[var(--control-text)]'>
                  {name}
                </Typography.Text>
              </div>
              {item.description && (
                <Typography.Text
                  className='block text-11px text-[var(--control-subtle)] line-clamp-2'
                  ellipsis
                >
                  {item.description}
                </Typography.Text>
              )}
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
              No {props.label} found
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
