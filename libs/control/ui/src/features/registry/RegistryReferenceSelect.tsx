import { Message, Select, Spin, Typography } from '@arco-design/web-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { NumberPageMeta } from '@/shared/types/api';

type RegistryOption = {
  label: string;
  value: string;
};

type NamedRegistryResource = {
  name?: string;
};

type RegistryReferenceSelectProps<TPage extends NumberPageMeta> = {
  resourceLabel: string;
  placeholder: string;
  value?: string | string[];
  onChange?: (value: string | string[]) => void;
  fetchPage: (params: { pageSize: number; pageNumber: number }) => Promise<TPage>;
  extractItems: (page: TPage) => NamedRegistryResource[];
  mode?: 'multiple';
  allowClear?: boolean;
  disabled?: boolean;
  pageSize?: number;
};

const DEFAULT_PAGE_SIZE = 50;
const LOAD_MORE_THRESHOLD = 24;

function normalizeSelectedNames(value?: string | string[]): string[] {
  if (Array.isArray(value)) {
    return Array.from(new Set(value.map((item) => item.trim()).filter(Boolean)));
  }
  if (typeof value === 'string' && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function mergeOptions(current: RegistryOption[], incomingNames: string[]): RegistryOption[] {
  const merged = new Map(current.map((item) => [item.value, item] as const));
  let changed = false;
  for (const name of incomingNames) {
    if (merged.has(name)) {
      continue;
    }
    merged.set(name, {
      value: name,
      label: name,
    });
    changed = true;
  }
  return changed ? Array.from(merged.values()) : current;
}

function deriveTotalPages(page: NumberPageMeta, pageSize: number): number | undefined {
  if (typeof page.total_pages === 'number' && page.total_pages > 0) {
    return page.total_pages;
  }
  if (typeof page.total_size === 'number' && page.total_size >= 0 && pageSize > 0) {
    return Math.ceil(page.total_size / pageSize);
  }
  return undefined;
}

export default function RegistryReferenceSelect<TPage extends NumberPageMeta>(
  props: RegistryReferenceSelectProps<TPage>,
) {
  const pageSize = props.pageSize ?? DEFAULT_PAGE_SIZE;
  const [options, setOptions] = useState<RegistryOption[]>([]);
  const [loadedPageNumber, setLoadedPageNumber] = useState(0);
  const [totalPages, setTotalPages] = useState<number | undefined>(undefined);
  const [totalSize, setTotalSize] = useState<number | undefined>(undefined);
  const [lastPageItemCount, setLastPageItemCount] = useState(0);
  const [loadingPage, setLoadingPage] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const loadingPageRef = useRef(false);

  const selectedNames = useMemo(() => normalizeSelectedNames(props.value), [props.value]);
  const selectedNamesKey = useMemo(() => selectedNames.join('\n'), [selectedNames]);
  const normalizedSearchValue = useMemo(() => searchValue.trim().toLowerCase(), [searchValue]);
  const hasMore = useMemo(() => {
    if (totalPages !== undefined) {
      return loadedPageNumber < totalPages;
    }
    if (loadedPageNumber === 0) {
      return true;
    }
    return lastPageItemCount >= pageSize;
  }, [lastPageItemCount, loadedPageNumber, pageSize, totalPages]);
  const hasLoadedSearchMatch = useMemo(() => {
    if (!normalizedSearchValue) {
      return true;
    }
    return options.some((item) => item.label.toLowerCase().includes(normalizedSearchValue));
  }, [normalizedSearchValue, options]);

  useEffect(() => {
    if (selectedNames.length === 0) {
      return;
    }
    setOptions((current) => mergeOptions(current, selectedNames));
  }, [selectedNamesKey]);

  const loadPage = useCallback(
    async (pageNumber: number) => {
      if (loadingPageRef.current) {
        return;
      }

      loadingPageRef.current = true;
      setLoadingPage(true);
      try {
        const page = await props.fetchPage({
          pageSize,
          pageNumber,
        });
        const itemNames = props.extractItems(page).flatMap((item) => {
          const name = item.name?.trim();
          return name ? [name] : [];
        });

        setOptions((current) => mergeOptions(current, itemNames));
        setLoadedPageNumber((current) => Math.max(current, pageNumber));
        setLastPageItemCount(itemNames.length);
        setTotalPages(deriveTotalPages(page, pageSize));
        setTotalSize(page.total_size);
      } catch (error) {
        Message.error(error instanceof Error ? error.message : `failed to load ${props.resourceLabel}`);
      } finally {
        loadingPageRef.current = false;
        setLoadingPage(false);
      }
    },
    [pageSize, props],
  );

  useEffect(() => {
    if (!normalizedSearchValue || hasLoadedSearchMatch || !hasMore || loadingPage || loadedPageNumber === 0) {
      return;
    }
    void loadPage(loadedPageNumber + 1);
  }, [hasLoadedSearchMatch, hasMore, loadPage, loadedPageNumber, loadingPage, normalizedSearchValue]);

  const footerText = useMemo(() => {
    if (loadingPage && loadedPageNumber === 0) {
      return `Loading ${props.resourceLabel}...`;
    }
    if (totalSize !== undefined) {
      if (hasMore) {
        return `Loaded ${options.length} / ${totalSize}. Scroll to load more.`;
      }
      return `${totalSize} ${props.resourceLabel} loaded.`;
    }
    if (hasMore) {
      return `Loaded ${options.length}. Scroll to load more ${props.resourceLabel}.`;
    }
    if (options.length > 0) {
      return `${options.length} ${props.resourceLabel} loaded.`;
    }
    return `No ${props.resourceLabel} available.`;
  }, [hasMore, loadedPageNumber, loadingPage, options.length, props.resourceLabel, totalSize]);

  return (
    <Select
      mode={props.mode}
      allowClear={props.allowClear}
      disabled={props.disabled}
      showSearch
      filterOption
      placeholder={props.placeholder}
      options={options}
      value={props.value}
      virtualListProps={{ height: 280 }}
      notFoundContent={
        loadingPage && (loadedPageNumber === 0 || Boolean(normalizedSearchValue)) ? (
          <div className='flex items-center justify-center py-12px'>
            <Spin size={16} />
          </div>
        ) : searchValue && hasMore ? (
          `No loaded ${props.resourceLabel} match. Continue scrolling to load more.`
        ) : (
          `No ${props.resourceLabel} found.`
        )
      }
      dropdownRender={(menu) => (
        <div>
          {menu}
          <div className='border-t border-[var(--control-border)] px-12px py-8px'>
            <Typography.Text className='text-12px text-[var(--control-subtle)]'>
              {footerText}
            </Typography.Text>
          </div>
        </div>
      )}
      onChange={(value) => {
        props.onChange?.(value as string | string[]);
      }}
      onSearch={(value) => {
        setSearchValue(value);
      }}
      onVisibleChange={(visible) => {
        if (!visible) {
          setSearchValue('');
          return;
        }
        if (loadedPageNumber === 0) {
          void loadPage(1);
        }
      }}
      onPopupScroll={(elem) => {
        if (!hasMore || loadingPage) {
          return;
        }
        const nearBottom = elem.scrollTop + elem.clientHeight >= elem.scrollHeight - LOAD_MORE_THRESHOLD;
        if (!nearBottom) {
          return;
        }
        void loadPage(loadedPageNumber + 1);
      }}
    />
  );
}
