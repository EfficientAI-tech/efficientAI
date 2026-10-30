'use client';

import Link from 'fumadocs-core/link';
import {
  Activity,
  AudioLines,
  BarChart3,
  Braces,
  ChevronDown,
  FileText,
  FlaskConical,
  LayoutGrid,
  Shield,
  Tag,
  Wrench,
} from 'lucide-react';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ChangelogBoardUpdate, ChangelogBoardWeek, ChangelogCategory } from '@/lib/changelog-board';
import { buildMonthAxis, calendarRatio, updateCountLabel } from '@/lib/changelog-board';

const ICONS: Record<ChangelogCategory, typeof Shield> = {
  Security: Shield,
  Observability: Activity,
  Voice: AudioLines,
  Usage: BarChart3,
  Evaluation: FlaskConical,
  API: Braces,
  Docs: FileText,
  Platform: LayoutGrid,
  Fixes: Wrench,
  Release: Tag,
};

const ICON_COLORS: Record<ChangelogCategory, { background: string; color: string }> = {
  Security: { background: '#fde68a', color: '#b45309' },
  Observability: { background: '#ffedd5', color: '#ea580c' },
  Voice: { background: '#dbeafe', color: '#1d4ed8' },
  Usage: { background: '#dcfce7', color: '#15803d' },
  Evaluation: { background: '#fce7f3', color: '#be185d' },
  API: { background: '#cffafe', color: '#0e7490' },
  Docs: { background: '#e0e7ff', color: '#4338ca' },
  Platform: { background: '#fef3c7', color: '#a16207' },
  Fixes: { background: '#fee2e2', color: '#b91c1c' },
  Release: { background: '#f3e8ff', color: '#7e22ce' },
};

type Props = {
  weeks: ChangelogBoardWeek[];
  categories: ChangelogCategory[];
  contributors: string[];
};

function stamp(update: ChangelogBoardUpdate) {
  return update.year * 10000 + update.month * 100 + update.day;
}

function earliest(updates: ChangelogBoardUpdate[]) {
  return updates.reduce((best, update) => (stamp(update) < stamp(best) ? update : best));
}

function latest(updates: ChangelogBoardUpdate[]) {
  return updates.reduce((best, update) => (stamp(update) > stamp(best) ? update : best));
}

export function ChangelogBoard({ weeks, categories, contributors }: Props) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [category, setCategory] = useState('all');
  const [contributor, setContributor] = useState('all');
  const [windowStart, setWindowStart] = useState(0);
  const [visibleCount, setVisibleCount] = useState(4);

  const visibleWeeks = useMemo(
    () =>
      weeks
        .map((week) => ({
          ...week,
          updates: week.updates.filter(
            (update) =>
              (category === 'all' || update.category === category) &&
              (contributor === 'all' || update.contributor === contributor),
          ),
        }))
        .filter((week) => week.updates.length > 0),
    [weeks, category, contributor],
  );

  const months = useMemo(
    () => buildMonthAxis(weeks.flatMap((week) => week.updates)),
    [weeks],
  );

  const yearLabels = useMemo(() => {
    const groups: Array<{ year: number; from: number; to: number }> = [];
    months.forEach((month, index) => {
      const last = groups[groups.length - 1];
      if (!last || last.year !== month.year) {
        groups.push({ year: month.year, from: index, to: index + 1 });
        return;
      }
      last.to = index + 1;
    });
    return groups.map((group) => ({
      year: group.year,
      center: ((group.from + group.to) / 2 / months.length) * 100,
    }));
  }, [months]);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    const measure = () => {
      const column = scroller.querySelector<HTMLElement>('[data-week]');
      const width = column?.offsetWidth ?? scroller.clientWidth;
      const visible = Math.max(1, Math.round(scroller.clientWidth / Math.max(width, 1)));
      const start = Math.round(scroller.scrollLeft / Math.max(width, 1));
      setVisibleCount(visible);
      setWindowStart(start);
    };

    const column = scroller.querySelector<HTMLElement>('[data-week]');
    const width = column?.offsetWidth ?? 0;
    const max = Math.max(0, scroller.scrollWidth - scroller.clientWidth);
    scroller.scrollLeft = width > 0 ? Math.min(max, Math.round(max / width) * width) : max;
    measure();

    const onScroll = () => measure();
    scroller.addEventListener('scroll', onScroll, { passive: true });
    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    return () => {
      scroller.removeEventListener('scroll', onScroll);
      observer.disconnect();
    };
  }, [visibleWeeks]);

  const scrollToIndex = (index: number) => {
    const scroller = scrollerRef.current;
    const column = scroller?.querySelector<HTMLElement>('[data-week]');
    if (!scroller || !column) return;
    const maxStart = Math.max(0, visibleWeeks.length - visibleCount);
    const next = Math.min(Math.max(0, index), maxStart);
    scroller.scrollTo({ left: next * column.offsetWidth, behavior: 'auto' });
  };

  const scrollToMonth = (year: number, month: number) => {
    const index = visibleWeeks.findIndex((week) =>
      week.updates.some((update) => update.year === year && update.month === month),
    );
    if (index >= 0) scrollToIndex(index);
  };

  const maxStart = Math.max(0, visibleWeeks.length - visibleCount);
  const pill = (() => {
    if (months.length === 0 || visibleWeeks.length === 0) return { left: 0, width: 100 };
    const start = Math.min(windowStart, visibleWeeks.length - 1);
    const end = Math.min(visibleWeeks.length - 1, start + visibleCount - 1);
    const first = earliest(visibleWeeks[start].updates);
    const last = latest(visibleWeeks[end].updates);
    const axisStart = months[0].start;
    const axisEnd = months[months.length - 1].end;
    const left = calendarRatio(first.year, first.month, first.day, axisStart, axisEnd) * 100;
    const right = calendarRatio(last.year, last.month, last.day, axisStart, axisEnd) * 100;
    const width = Math.max(12, right - left + 100 / months.length);
    return { left: Math.min(left, 100 - width), width: Math.min(width, 100) };
  })();

  return (
    <section className="changelog-board overflow-hidden rounded-xl border border-fd-border bg-white shadow-[0_18px_50px_-28px_rgba(0,0,0,0.45)] dark:bg-fd-card">
      <div className="flex flex-wrap items-end justify-between gap-3 px-4 pt-3.5 pb-3">
        <div className="min-w-0">
          <h1 className="!m-0 !text-[0.95rem] !leading-snug !font-semibold !tracking-tight">Changelog</h1>
          <div className="mt-3 flex flex-wrap gap-2">
            <FilterSelect
              label="Category"
              value={category}
              onChange={setCategory}
              options={[{ value: 'all', label: 'All categories' }, ...categories.map((item) => ({ value: item, label: item }))]}
            />
            <FilterSelect
              label="Contributor"
              value={contributor}
              onChange={setContributor}
              options={[
                { value: 'all', label: 'All contributors' },
                ...contributors.map((item) => ({ value: item, label: item })),
              ]}
            />
          </div>
        </div>
        <div className="pb-1 text-sm text-fd-muted-foreground">
          Also available on{' '}
          <a className="changelog-text-link" href="https://github.com/EfficientAI-tech/efficientAI/releases">
            GitHub
          </a>
        </div>
      </div>

      {visibleWeeks.length === 0 ? (
        <p className="border-t border-fd-border px-4 py-16 text-center text-sm text-fd-muted-foreground">
          No updates match these filters.
        </p>
      ) : (
        <div
          ref={scrollerRef}
          className="changelog-board-columns flex h-[min(24rem,calc(100dvh-18rem))] snap-x snap-mandatory overflow-auto border-t border-fd-border md:h-[min(36rem,calc(100dvh-16rem))]"
        >
          {visibleWeeks.map((week) => (
            <article
              key={week.id}
              data-week={week.id}
              className="flex min-h-full shrink-0 grow-0 basis-full snap-start flex-col border-r border-fd-border last:border-r-0 md:basis-1/2 xl:basis-1/4"
              aria-label={week.title}
            >
              <header className="sticky top-0 z-10 bg-white px-3 pt-3 pb-2 dark:bg-fd-card">
                <div className="text-sm font-semibold tracking-tight text-fd-foreground">{week.title}</div>
                <div className="mt-0.5 text-xs text-fd-muted-foreground">
                  {updateCountLabel(week.id, week.updates.length)}
                </div>
              </header>
              <div>
                {week.updates.map((update) => (
                  <UpdateRow key={update.id} update={update} />
                ))}
              </div>
            </article>
          ))}
        </div>
      )}

      {months.length > 0 ? (
        <div className="relative border-t border-fd-border px-3 pt-2 pb-2.5">
          <div className="relative h-4">
            {yearLabels.map((label) => (
              <span
                key={label.year}
                className="absolute top-0 -translate-x-1/2 bg-white px-1.5 text-[11px] font-medium text-fd-foreground dark:bg-fd-card"
                style={{ left: `${label.center}%` }}
              >
                {label.year}
              </span>
            ))}
          </div>
          <div className="relative mt-1 h-7">
            <div
              className="pointer-events-none absolute top-0.5 h-5 rounded-md border border-neutral-300 bg-white shadow-sm dark:border-white/30 dark:bg-white/10"
              style={{ left: `${pill.left}%`, width: `${pill.width}%` }}
            />
            <div className="pointer-events-none absolute inset-x-0 top-2 flex">
              {months.map((month) => (
                <div key={month.key} className="flex flex-1 justify-center">
                  <span
                    className={month.hasUpdates ? 'h-2.5 w-1.5 rounded-[1px] bg-emerald-600' : 'h-2.5 w-1.5 rounded-[1px] bg-neutral-300 dark:bg-neutral-600'}
                  />
                </div>
              ))}
            </div>
            <input
              className="absolute inset-x-0 top-0 z-10 h-6 w-full cursor-ew-resize appearance-none opacity-0"
              type="range"
              min={0}
              max={maxStart}
              value={Math.min(windowStart, maxStart)}
              aria-label="Changelog timeline"
              aria-valuetext={visibleWeeks[Math.min(windowStart, visibleWeeks.length - 1)]?.title ?? 'Changelog'}
              onChange={(event) => scrollToIndex(Number(event.target.value))}
            />
          </div>
          <div className="flex">
            {months.map((month) => (
              <button
                key={month.key}
                type="button"
                className="flex-1 text-center text-[10px] text-fd-muted-foreground hover:text-fd-foreground"
                onClick={() => scrollToMonth(month.year, month.month)}
              >
                {month.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="relative inline-flex">
      <span className="sr-only">{label}</span>
      <select
        className="h-8 appearance-none rounded-md border border-fd-border bg-white pe-7 ps-2.5 text-sm text-fd-foreground dark:bg-fd-card"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute end-2 top-1/2 size-3.5 -translate-y-1/2 text-fd-muted-foreground" />
    </label>
  );
}

function UpdateRow({ update }: { update: ChangelogBoardUpdate }) {
  const Icon = ICONS[update.category];
  const colors = ICON_COLORS[update.category];

  return (
    <Link
      href={update.href}
      className="!flex !items-center !gap-3 !border-t !border-fd-border/80 !px-3 !py-2.5 !font-normal !text-inherit !no-underline hover:!bg-[#f3f4f6] focus-visible:!bg-[#f3f4f6] focus-visible:!outline-none dark:hover:!bg-white/[0.06] dark:focus-visible:!bg-white/[0.06]"
      aria-label={`${update.title}, ${update.category}, ${update.version}`}
    >
      <span className="min-w-0 flex-1">
        <span className="block text-[13.5px] leading-snug font-semibold wrap-anywhere text-fd-foreground line-clamp-2">
          {update.title}
        </span>
        <span className="mt-0.5 block text-xs leading-4 text-fd-muted-foreground">{update.category}</span>
      </span>
      <span
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-md"
        style={{ background: colors.background, color: colors.color }}
        aria-hidden
      >
        <Icon className="size-4" strokeWidth={2.25} />
      </span>
    </Link>
  );
}
