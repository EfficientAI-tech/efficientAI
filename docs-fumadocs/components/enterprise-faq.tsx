import { ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';

type FaqItem = {
  question: string;
  answer: ReactNode;
};

const FAQ_ITEMS: FaqItem[] = [
  {
    question: 'What happens if no Enterprise license is configured?',
    answer: (
      <>
        Open-source limits still apply (for example, agent and metric caps, single-member organizations,
        and seven-day usage analytics retention). Routes that require Enterprise return HTTP{' '}
        <code className="text-[11px] px-1 py-0.5 rounded bg-fd-muted">403</code> when the deployment or
        organization is not entitled.
      </>
    ),
  },
  {
    question: 'What is the open-source limit on usage analytics?',
    answer:
      'Self-hosted open-source deployments retain usage analytics for the most recent seven days. Enterprise removes that retention cap.',
  },
  {
    question: 'Is GEPA or prompt optimization limited to Enterprise?',
    answer:
      'No. GEPA and prompt optimization are included in the open-source Business Source License distribution.',
  },
  {
    question: 'How do I confirm that my organization is licensed?',
    answer: (
      <>
        After you configure <code className="text-[11px] px-1 py-0.5 rounded bg-fd-muted">EFFICIENTAI_LICENSE</code>,
        call <code className="text-[11px] px-1 py-0.5 rounded bg-fd-muted">GET /api/v1/license-info</code> and
        review the enabled entitlements for your deployment or organization scope.
      </>
    ),
  },
  {
    question: 'Where do I configure enterprise authentication?',
    answer: (
      <>
        See the{' '}
        <a href="/docs/getting-started/authentication/" className="font-medium underline underline-offset-2">
          Authentication guide
        </a>{' '}
        and the{' '}
        <a href="/docs/reference/configuration/" className="font-medium underline underline-offset-2">
          Configuration reference
        </a>{' '}
        for OIDC, SAML, SCIM, and related settings.
      </>
    ),
  },
];

export function EnterpriseFaq() {
  return (
    <div className="not-prose enterprise-faq my-6 flex flex-col gap-2">
      {FAQ_ITEMS.map((item) => (
        <details
          key={item.question}
          className="enterprise-faq-item group rounded-xl border border-fd-border bg-fd-card shadow-sm ring-1 ring-fd-border/40 open:ring-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_22%,var(--color-fd-border))]"
        >
          <summary
            className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3.5 text-sm font-semibold text-fd-foreground marker:content-none [&::-webkit-details-marker]:hidden"
          >
            <span className="text-left leading-snug">{item.question}</span>
            <ChevronDown
              className="size-4 shrink-0 text-fd-muted-foreground transition-transform duration-200 group-open:rotate-180"
              aria-hidden
            />
          </summary>
          <div className="border-t border-fd-border/80 px-4 py-3.5 text-sm leading-relaxed text-fd-muted-foreground">
            {item.answer}
          </div>
        </details>
      ))}
    </div>
  );
}
