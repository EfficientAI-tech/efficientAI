import { Check, Minus, Sparkles } from 'lucide-react';
type PlanCell =
  | { type: 'yes'; detail?: string }
  | { type: 'no' }
  | { type: 'text'; value: string };

type ComparisonRow = {
  feature: string;
  oss: PlanCell;
  enterprise: PlanCell;
};

type ComparisonSection = {
  title: string;
  rows: ComparisonRow[];
};

const SECTIONS: ComparisonSection[] = [
  {
    title: 'Evaluation core',
    rows: [
      {
        feature: 'Voice bundles & BYOK integrations',
        oss: { type: 'yes' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'Agents',
        oss: { type: 'text', value: 'Up to **3** agents' },
        enterprise: { type: 'yes', detail: 'Unlimited' },
      },
      {
        feature: 'Custom metrics',
        oss: { type: 'text', value: 'Up to **5** metrics' },
        enterprise: { type: 'yes', detail: 'Unlimited' },
      },
      {
        feature: 'Evaluators, suites & results',
        oss: { type: 'yes' },
        enterprise: { type: 'yes', detail: '+ failure clustering' },
      },
      {
        feature: 'Prompt partials',
        oss: { type: 'yes' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'GEPA / prompt optimization',
        oss: { type: 'yes' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'Agent playground',
        oss: { type: 'yes' },
        enterprise: { type: 'yes' },
      },
    ],
  },
  {
    title: 'Production & analytics',
    rows: [
      {
        feature: 'Voice playground (blind testing)',
        oss: { type: 'no' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'Call imports',
        oss: { type: 'no' },
        enterprise: { type: 'yes', detail: 'Post-production analytics' },
      },
      {
        feature: 'Metric Studio',
        oss: { type: 'no' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'Alerts',
        oss: { type: 'no' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'Usage analytics history',
        oss: { type: 'text', value: 'Last **7 days**' },
        enterprise: { type: 'yes', detail: 'Unlimited retention' },
      },
    ],
  },
  {
    title: 'Organization & platform',
    rows: [
      {
        feature: 'Org members',
        oss: { type: 'text', value: '**1** member per org' },
        enterprise: { type: 'yes', detail: 'Unlimited' },
      },
      {
        feature: 'Workspaces',
        oss: { type: 'text', value: '**1** default workspace' },
        enterprise: { type: 'yes', detail: 'Unlimited' },
      },
      {
        feature: 'Gateway enablement (integrations)',
        oss: { type: 'no' },
        enterprise: { type: 'yes' },
      },
      {
        feature: 'Authentication',
        oss: {
          type: 'text',
          value: 'API keys + local email/password',
        },
        enterprise: {
          type: 'yes',
          detail: 'OIDC, SAML, SCIM, MFA, audit export',
        },
      },
    ],
  },
];

const GATED_FEATURES = [
  {
    id: 'call_imports',
    title: 'Call imports',
    description: 'Post-production call imports and batch analytics.',
  },
  {
    id: 'voice_playground',
    title: 'Voice playground',
    description: 'Blind TTS comparison and voice playground workflows.',
  },
] as const;

function RichText({ value }: { value: string }) {
  const parts = value.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={i} className="font-semibold text-fd-foreground">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

function PlanCellView({ cell, column }: { cell: PlanCell; column: 'oss' | 'enterprise' }) {
  if (cell.type === 'no') {
    return (
      <span
        className="inline-flex items-center justify-center gap-1.5 text-fd-muted-foreground"
        aria-label="Not included"
      >
        <Minus className="size-4 shrink-0 opacity-60" strokeWidth={2.5} />
        <span className="text-xs sm:text-sm">—</span>
      </span>
    );
  }

  if (cell.type === 'text') {
    return (
      <span className="text-xs sm:text-sm leading-snug text-fd-foreground/90 text-center sm:text-left">
        <RichText value={cell.value} />
      </span>
    );
  }

  const checkClass =
    column === 'enterprise'
      ? 'text-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_85%,#16a34a)]'
      : 'text-emerald-600 dark:text-emerald-400';

  return (
    <div className="flex flex-col items-center sm:items-start gap-0.5">
      <Check className={`size-5 shrink-0 ${checkClass}`} strokeWidth={2.5} aria-hidden />
      {cell.detail ? (
        <span className="text-[11px] sm:text-xs leading-tight text-fd-muted-foreground text-center sm:text-left max-w-[11rem]">
          {cell.detail}
        </span>
      ) : null}
    </div>
  );
}

function ComparisonHeader() {
  return (
    <div
      className="enterprise-comparison-header grid grid-cols-[minmax(0,1.4fr)_minmax(5.5rem,1fr)_minmax(5.5rem,1fr)] sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 sm:gap-4 px-3 sm:px-5 py-4 border-b border-fd-border bg-fd-muted/40"
      role="row"
    >
      <div className="text-xs font-semibold uppercase tracking-wide text-fd-muted-foreground self-end pb-0.5">
        Capability
      </div>
      <div
        className="text-center rounded-lg border border-fd-border bg-fd-card px-2 py-2.5 shadow-sm"
        role="columnheader"
      >
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-fd-muted-foreground">
          Open source
        </span>
        <span className="block text-xs text-fd-foreground/80 mt-0.5">BSL</span>
      </div>
      <div
        className="enterprise-comparison-enterprise-col text-center rounded-lg border px-2 py-2.5 shadow-sm"
        role="columnheader"
      >
        <span className="inline-flex items-center justify-center gap-1 text-[11px] font-semibold uppercase tracking-wide">
          <Sparkles className="size-3.5 opacity-90" aria-hidden />
          Enterprise
        </span>
        <span className="block text-xs opacity-90 mt-0.5">Licensed</span>
      </div>
    </div>
  );
}

function ComparisonRowView({ row }: { row: ComparisonRow }) {
  return (
    <div
      className="enterprise-comparison-row grid grid-cols-[minmax(0,1.4fr)_minmax(5.5rem,1fr)_minmax(5.5rem,1fr)] sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 sm:gap-4 px-3 sm:px-5 py-3.5 sm:py-4 items-center border-b border-fd-border/80 last:border-b-0"
      role="row"
    >
      <div className="text-sm font-medium text-fd-foreground leading-snug pr-1" role="rowheader">
        {row.feature}
      </div>
      <div className="flex justify-center sm:justify-start" role="cell">
        <PlanCellView cell={row.oss} column="oss" />
      </div>
      <div
        className="enterprise-comparison-enterprise-cell flex justify-center sm:justify-start rounded-lg -mx-1 px-1 py-1"
        role="cell"
      >
        <PlanCellView cell={row.enterprise} column="enterprise" />
      </div>
    </div>
  );
}

export function EnterpriseComparison() {
  return (
    <div className="not-prose enterprise-comparison my-8 w-full">
      <div
        className="overflow-x-auto rounded-xl border border-fd-border bg-fd-card shadow-sm ring-1 ring-fd-border/50"
        tabIndex={0}
        aria-label="Open source versus Enterprise feature comparison"
      >
        <div className="min-w-[320px] sm:min-w-0">
          <ComparisonHeader />
          {SECTIONS.map((section) => (
            <div key={section.title} className="enterprise-comparison-section">
              <div
                className="px-3 sm:px-5 py-2.5 bg-fd-muted/25 border-b border-fd-border/70 text-xs font-semibold uppercase tracking-wider text-fd-muted-foreground"
                role="row"
              >
                {section.title}
              </div>
              {section.rows.map((row) => (
                <ComparisonRowView key={row.feature} row={row} />
              ))}
            </div>
          ))}
        </div>
      </div>
      <p className="mt-3 text-xs text-fd-muted-foreground leading-relaxed max-w-3xl">
        Limits apply automatically in open-source deployments. Enterprise unlocks caps and gated
        routes when <code className="text-[11px] px-1 py-0.5 rounded bg-fd-muted">EFFICIENTAI_LICENSE</code>{' '}
        is configured for your org.
      </p>
    </div>
  );
}

export function EnterpriseGatedFeatures() {
  return (
    <div className="not-prose enterprise-gated my-6 grid gap-3 sm:grid-cols-2">
      {GATED_FEATURES.map((item) => (
        <div
          key={item.id}
          className="rounded-xl border border-fd-border bg-fd-card p-4 shadow-sm ring-1 ring-fd-border/40 transition-colors hover:border-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_35%,var(--color-fd-border))]"
        >
          <div className="flex items-start gap-3">
            <span
              className="shrink-0 rounded-md border border-fd-border bg-fd-muted px-2 py-1 font-mono text-[11px] text-fd-foreground"
            >
              {item.id}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-fd-foreground">{item.title}</p>
              <p className="text-xs text-fd-muted-foreground mt-1 leading-relaxed">{item.description}</p>
            </div>
            <Check
              className="size-4 shrink-0 mt-0.5 text-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_70%,#16a34a)]"
              strokeWidth={2.5}
              aria-hidden
            />
          </div>
        </div>
      ))}
    </div>
  );
}
