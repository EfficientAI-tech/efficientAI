import Link from 'fumadocs-core/link';

type Provider = {
  id: string;
  label: string;
  href: string;
  logo?: string;
};

const providers: Provider[] = [
  { id: 'overview', label: 'Overview', href: '/docs/integrations/' },
  { id: 'retell', label: 'Retell', href: '/docs/integrations/retell/', logo: '/retellai.png' },
  { id: 'elevenlabs', label: 'ElevenLabs', href: '/docs/integrations/elevenlabs/', logo: '/elevenlabs.jpg' },
  { id: 'vapi', label: 'Vapi', href: '/docs/integrations/vapi/', logo: '/vapiai.jpg' },
  { id: 'smallest', label: 'Smallest', href: '/docs/integrations/smallest/', logo: '/smallest.jpeg' },
  { id: 'plivo', label: 'Plivo', href: '/docs/integrations/plivo/', logo: '/plivo.png' },
  { id: 'vobiz', label: 'Vobiz', href: '/docs/integrations/vobiz/', logo: '/vobiz.png' },
];

export function IntegrationProviderNav({ active }: { active: Provider['id'] }) {
  return (
    <div className="not-prose mb-5 overflow-x-auto rounded-lg bg-fd-card/20 p-2">
      <div className="flex min-w-max items-center gap-2">
        {providers.map((provider) => {
          const isActive = provider.id === active;
          return (
            <Link
              key={provider.id}
              href={provider.href}
              className={[
                'inline-flex items-center gap-2 rounded-md border border-transparent px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-fd-primary/10 text-fd-primary'
                  : 'text-fd-muted-foreground hover:bg-fd-accent/40 hover:text-fd-foreground',
              ].join(' ')}
            >
              {provider.logo ? (
                <img
                  src={provider.logo}
                  alt={`${provider.label} logo`}
                  className="h-3.5 w-6 object-contain"
                  loading="lazy"
                />
              ) : null}
              <span>{provider.label}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
