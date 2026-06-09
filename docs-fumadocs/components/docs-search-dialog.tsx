'use client';

import { useOnChange } from 'fumadocs-core/utils/use-on-change';
import {
  SearchDialog,
  SearchDialogClose,
  SearchDialogContent,
  SearchDialogFooter,
  SearchDialogHeader,
  SearchDialogIcon,
  SearchDialogInput,
  SearchDialogList,
  SearchDialogOverlay,
  TagsList,
  TagsListItem,
} from 'fumadocs-ui/components/dialog/search';
import type { SearchLink, SharedProps, TagItem } from 'fumadocs-ui/contexts/search';
import { useEffect, useMemo, useState } from 'react';

type SearchRecord = {
  id: string;
  url: string;
  title: string;
  breadcrumbs?: string[];
  content?: string;
};

type SearchItem = {
  type: 'page';
  id: string;
  content: string;
  breadcrumbs?: string[];
  url: string;
};

type DocsSearchDialogProps = SharedProps & {
  defaultTag?: string;
  tags?: TagItem[];
  api?: string;
  delayMs?: number;
  footer?: React.ReactNode;
  links?: SearchLink[];
  allowClear?: boolean;
};

export function DocsSearchDialog({
  defaultTag,
  tags = [],
  api,
  delayMs,
  allowClear = false,
  links = [],
  footer,
  ...props
}: DocsSearchDialogProps) {
  const [tag, setTag] = useState(defaultTag);
  const [search, setSearch] = useState('');
  const [records, setRecords] = useState<SearchRecord[] | null>(null);
  const [results, setResults] = useState<SearchItem[] | 'empty'>('empty');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const indexPath = api ?? '/search-index.json';

    setIsLoading(true);
    fetch(indexPath)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load search index from ${indexPath}`);
        }
        return response.json();
      })
      .then((data: unknown) => {
        if (cancelled) return;
        const raw = Array.isArray(data)
          ? data
          : Array.isArray((data as { records?: unknown[] })?.records)
            ? (data as { records: unknown[] }).records
            : [];
        const parsed = raw.filter(
          (record): record is SearchRecord =>
            typeof record === 'object' &&
            record !== null &&
            typeof (record as SearchRecord).id === 'string' &&
            typeof (record as SearchRecord).url === 'string' &&
            typeof (record as SearchRecord).title === 'string',
        );
        setRecords(parsed);
      })
      .catch(() => {
        if (!cancelled) setRecords([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [api]);

  useEffect(() => {
    if (!records) return;
    const query = search.trim().toLowerCase();
    if (query.length === 0) {
      setResults('empty');
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    const timer = window.setTimeout(() => {
      const ranked = records
        .map((record) => {
          const title = record.title.toLowerCase();
          const breadcrumbs = (record.breadcrumbs ?? []).join(' ').toLowerCase();
          const content = (record.content ?? '').toLowerCase();
          let score = 0;
          if (title.startsWith(query)) score += 80;
          else if (title.includes(query)) score += 50;
          if (breadcrumbs.includes(query)) score += 20;
          if (content.includes(query)) score += 12;
          return { record, score };
        })
        .filter((entry) => entry.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 25)
        .map((entry) => ({
          type: 'page' as const,
          id: entry.record.id,
          content: entry.record.title,
          breadcrumbs: entry.record.breadcrumbs,
          url: entry.record.url,
        }));

      setResults(ranked);
      setIsLoading(false);
    }, delayMs ?? 120);

    return () => {
      window.clearTimeout(timer);
    };
  }, [delayMs, records, search]);

  const defaultItems = useMemo(() => {
    if (links.length === 0) return null;
    return links.map(([name, link]) => ({
      type: 'page' as const,
      id: name,
      content: name,
      url: link,
    }));
  }, [links]);

  useOnChange(defaultTag, (nextTag) => {
    setTag(nextTag);
  });

  return (
    <SearchDialog search={search} onSearchChange={setSearch} isLoading={isLoading} {...props}>
      <SearchDialogOverlay />
      <SearchDialogContent>
        <SearchDialogHeader>
          <SearchDialogIcon />
          <SearchDialogInput />
          <SearchDialogClose />
        </SearchDialogHeader>
        <SearchDialogList items={results !== 'empty' ? results : defaultItems} />
      </SearchDialogContent>
      <SearchDialogFooter>
        {tags.length > 0 ? (
          <TagsList tag={tag} onTagChange={setTag} allowClear={allowClear}>
            {tags.map((tagItem) => (
              <TagsListItem key={tagItem.value} value={tagItem.value}>
                {tagItem.name}
              </TagsListItem>
            ))}
          </TagsList>
        ) : null}
        {footer}
      </SearchDialogFooter>
    </SearchDialog>
  );
}
