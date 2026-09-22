const FEATURE_ALIASES: Record<string, string> = {
  platform: 'intro',
  'platform/index': 'intro',
  'platform/agent': 'products/agents',
  'platform/persona': 'products/personas',
  'platform/scenario': 'products/scenarios',
  'platform/evaluator': 'products/evaluators',
  'platform/evaluation-suite': 'products/evaluators',
  'platform/metrics': 'products/metrics',
  'platform/playground': 'products/playground',
  'platform/prompts': 'products/prompt-partials',
  quickstart: 'getting-started/installation',
  'key-concepts': 'intro',
  'key-concepts/index': 'intro',
  integrations: 'getting-started/integrations',
  'integrations/index': 'getting-started/integrations',
  'integrations/retell': 'getting-started/integrations',
  'integrations/vapi': 'getting-started/integrations',
  'integrations/elevenlabs': 'getting-started/integrations',
  'integrations/plivo': 'getting-started/integrations',
  'integrations/smallest': 'getting-started/integrations',
  'integrations/vobiz': 'getting-started/integrations',
  enterprise: 'enterprise/overview',
  'enterprise/index': 'enterprise/overview',
  blog: 'intro',
  'blog/index': 'intro',
  changelog: 'intro',
  'changelog/index': 'intro',
  'api-reference': 'reference/configuration',
  'api-reference/agents': 'products/agents',
  'api-reference/personas': 'products/personas',
  'api-reference/scenarios': 'products/scenarios',
  'api-reference/evaluators': 'products/evaluators',
  'api-reference/evaluator-suites': 'products/evaluators',
  'api-reference/evaluator-results': 'products/evaluators',
  'api-reference/metrics': 'products/metrics',
  'api-reference/authentication': 'getting-started/authentication',
  'api-reference/observability': 'monitoring/calls',
  'api-reference/call-imports': 'enterprise/call-imports',
  'api-reference/workspaces': 'getting-started/workspaces',
  'api-reference/integrations': 'getting-started/integrations',
  'api-reference/voice-bundles': 'getting-started/voice-bundles',
  'api-reference/ai-providers': 'reference/configuration',
};

export function resolveFeatureId(slugPath: string): string {
  const normalized = slugPath.replace(/\/index$/, '').replace(/\/$/, '');

  if (FEATURE_ALIASES[normalized]) {
    return FEATURE_ALIASES[normalized];
  }

  const apiMatch = normalized.match(/^api-reference\/([^/]+)/);
  if (apiMatch) {
    const tagKey = `api-reference/${apiMatch[1]}`;
    if (FEATURE_ALIASES[tagKey]) {
      return FEATURE_ALIASES[tagKey];
    }
  }

  return normalized;
}
