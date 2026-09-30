#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const docsRoot = path.resolve(__dirname, '..');
const inputSchemaPath = path.join(docsRoot, 'openapi', 'openapi.json');
const outputSchemaPath = path.join(docsRoot, 'openapi', 'efficientai.json');
const markdownRoot = path.join(docsRoot, 'public', 'api-md');

const curatedTags = [
  {
    source: 'Authentication',
    slug: 'authentication',
    displayName: 'Authentication',
    description: 'Session and API-key authentication endpoints.',
  },
  { source: 'Workspaces', slug: 'workspaces', displayName: 'Workspaces', description: 'Workspace management endpoints.' },
  {
    source: 'Integrations',
    slug: 'integrations',
    displayName: 'Integrations',
    description: 'Voice, telephony, and provider integration endpoints.',
  },
  { source: 'agents', slug: 'agents', displayName: 'Agents', description: 'Agent configuration and lifecycle endpoints.' },
  { source: 'personas', slug: 'personas', displayName: 'Personas', description: 'Persona management endpoints.' },
  { source: 'scenarios', slug: 'scenarios', displayName: 'Scenarios', description: 'Scenario creation and management endpoints.' },
  { source: 'evaluators', slug: 'evaluators', displayName: 'Evaluators', description: 'Evaluator configuration endpoints.' },
  {
    source: 'evaluator-suites',
    slug: 'evaluator-suites',
    displayName: 'Evaluator Suites',
    description: 'Suite-level test combination management endpoints.',
  },
  {
    source: 'evaluator-results',
    slug: 'evaluator-results',
    displayName: 'Evaluator Results',
    description: 'Run and score retrieval endpoints.',
  },
  { source: 'metrics', slug: 'metrics', displayName: 'Metrics', description: 'Metric definition and execution endpoints.' },
  {
    source: 'observability',
    slug: 'observability',
    displayName: 'Observability',
    description: 'Call logs, traces, and observability endpoints.',
  },
  { source: 'Call Imports', slug: 'call-imports', displayName: 'Call Imports', description: 'Historical call import workflows.' },
  {
    source: 'voicebundles',
    slug: 'voice-bundles',
    displayName: 'Voice Bundles',
    description: 'Voice bundle configuration endpoints.',
  },
  {
    source: 'aiproviders',
    slug: 'ai-providers',
    displayName: 'AI Providers',
    description: 'Provider and model credentials endpoints.',
  },
];

const curatedTagSet = new Set(curatedTags.map((item) => item.source));
const tagBySource = new Map(curatedTags.map((item) => [item.source, item]));
const defaultServerUrl = process.env.DOCS_API_URL ?? 'http://localhost:8000';
const cloudServerUrl = process.env.DOCS_CLOUD_API_URL;
const publicRoutes = new Set([
  'GET /api/v1/auth/config',
  'POST /api/v1/auth/login',
  'POST /api/v1/auth/signup',
  'POST /api/v1/auth/refresh',
  'GET /api/v1/auth/invitations/preview/{token}',
]);
const httpMethods = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head'];

const selectedInputPath = fs.existsSync(inputSchemaPath) ? inputSchemaPath : outputSchemaPath;
if (!fs.existsSync(selectedInputPath)) {
  throw new Error(
    `Missing OpenAPI schema. Expected ${inputSchemaPath} (from openapi:export) or ${outputSchemaPath} (committed curated spec).`,
  );
}

const schema = JSON.parse(fs.readFileSync(selectedInputPath, 'utf8'));
const output = {
  ...schema,
  info: {
    ...schema.info,
    title: 'EfficientAI Platform API',
  },
  paths: {},
};

const markdownArtifacts = [];

for (const [routePath, pathItem] of Object.entries(schema.paths ?? {})) {
  const nextPathItem = {};
  if (Array.isArray(pathItem?.parameters)) nextPathItem.parameters = pathItem.parameters;

  for (const method of httpMethods) {
    const operation = pathItem?.[method];
    if (!operation) continue;

    const rawTags = Array.isArray(operation.tags) ? operation.tags : [];
    const tags = rawTags
      .map((tag) => (tag === 'observability-traces' ? 'observability' : tag))
      .filter((tag) => curatedTagSet.has(tag));
    if (tags.length === 0) continue;

    const opKey = `${method.toUpperCase()} ${routePath}`;
    const nextOperation = { ...operation, tags };

    if (publicRoutes.has(opKey)) {
      nextOperation.security = [];
    } else {
      nextOperation.parameters = addWorkspaceHeader(nextOperation.parameters);
    }

    nextPathItem[method] = nextOperation;
    addMarkdownArtifacts(markdownArtifacts, tags, method, routePath, nextOperation);
  }

  if (Object.keys(nextPathItem).some((key) => key === 'parameters' || httpMethods.includes(key))) {
    output.paths[routePath] = nextPathItem;
  }
}

output.tags = curatedTags.map((tag) => ({
  name: tag.source,
  description: tag.description,
  'x-displayName': tag.displayName,
}));

const existingComponents = output.components ?? {};
output.components = {
  ...existingComponents,
  securitySchemes: {
    ...(existingComponents.securitySchemes ?? {}),
    BearerAuth: {
      type: 'http',
      scheme: 'bearer',
      bearerFormat: 'JWT',
      description: 'JWT access token. Use: Authorization: Bearer <token>.',
    },
    ApiKeyAuth: {
      type: 'apiKey',
      in: 'header',
      name: 'X-API-Key',
      description: 'Organization API key generated from the authentication/settings surface.',
    },
  },
  parameters: {
    ...(existingComponents.parameters ?? {}),
    WorkspaceIdHeader: {
      name: 'X-Workspace-Id',
      in: 'header',
      required: false,
      schema: { type: 'string', format: 'uuid' },
      description:
        'Optional workspace scope. When omitted, the backend uses the active/default workspace from your organization context.',
    },
  },
};

output.security = [{ BearerAuth: [] }, { ApiKeyAuth: [] }];
output.servers = [
  { url: defaultServerUrl, description: 'Self-hosted' },
  ...(cloudServerUrl ? [{ url: cloudServerUrl, description: 'Cloud' }] : []),
];

pruneComponents(output);

const requiredObservabilityPaths = [
  '/api/v1/observability/traces',
  '/api/v1/observability/traces/setup',
  '/api/v1/observability/traces/sessions',
  '/api/v1/observability/calls-hub',
];
const missingPaths = requiredObservabilityPaths.filter((p) => !output.paths[p]);
if (missingPaths.length > 0) {
  throw new Error(
    `OpenAPI enrich: missing observability paths (re-run openapi:export from app): ${missingPaths.join(', ')}`,
  );
}

fs.mkdirSync(path.dirname(outputSchemaPath), { recursive: true });
fs.writeFileSync(outputSchemaPath, `${JSON.stringify(output, null, 2)}\n`, 'utf8');

fs.rmSync(markdownRoot, { recursive: true, force: true });
for (const artifact of markdownArtifacts) {
  const target = path.join(markdownRoot, artifact.relPath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, artifact.content, 'utf8');
}

console.log(
  `Enriched OpenAPI spec written to ${path.relative(docsRoot, outputSchemaPath)} with ${Object.keys(output.paths).length} paths (source: ${path.relative(docsRoot, selectedInputPath)}).`,
);
console.log(`Generated ${markdownArtifacts.length} markdown endpoint artifacts in ${path.relative(docsRoot, markdownRoot)}.`);

function addWorkspaceHeader(parameters) {
  const next = Array.isArray(parameters) ? [...parameters] : [];
  const hasWorkspaceHeader = next.some((param) => {
    if (!param || typeof param !== 'object') return false;
    if ('$ref' in param && typeof param.$ref === 'string') return param.$ref === '#/components/parameters/WorkspaceIdHeader';
    return param.in === 'header' && param.name === 'X-Workspace-Id';
  });
  if (!hasWorkspaceHeader) next.push({ $ref: '#/components/parameters/WorkspaceIdHeader' });
  return next;
}

function normalizeOperationFileName(operationId, method, routePath) {
  if (operationId && operationId.trim().length > 0) return operationId.trim();
  return `${routePathToFilePath(routePath)}/${method.toLowerCase()}`.replaceAll('/', '-');
}

function routePathToFilePath(routePath) {
  return routePath
    .toLowerCase()
    .replaceAll('.', '-')
    .split('/')
    .flatMap((segment) => {
      if (segment.startsWith('{') && segment.endsWith('}')) return [segment.slice(1, -1)];
      return [segment];
    })
    .filter(Boolean)
    .join('/');
}

function addMarkdownArtifacts(artifacts, tags, method, routePath, operation) {
  const fileName = normalizeOperationFileName(operation.operationId, method, routePath);
  const lines = [];
  lines.push(`# ${method.toUpperCase()} ${routePath}`);
  lines.push('');
  lines.push(operation.summary || operation.description || operation.operationId || 'No summary provided.');
  lines.push('');
  lines.push(`- Operation ID: \`${operation.operationId || 'n/a'}\``);
  lines.push(`- Tags: ${tags.map((tag) => `\`${tagBySource.get(tag)?.displayName ?? tag}\``).join(', ')}`);
  lines.push(`- Auth: ${publicRoutes.has(`${method.toUpperCase()} ${routePath}`) ? 'Public' : 'Bearer or API Key'}`);
  lines.push('');

  const params = collectParameters(operation.parameters);
  if (params.length > 0) {
    lines.push('## Parameters');
    lines.push('');
    for (const parameter of params) {
      const required = parameter.required ? 'required' : 'optional';
      const schemaType = parameter.schema?.type ? ` \`${parameter.schema.type}\`` : '';
      lines.push(`- \`${parameter.name}\` (${parameter.in}, ${required})${schemaType}`);
      if (parameter.description) lines.push(`  - ${parameter.description.replace(/\s+/g, ' ').trim()}`);
    }
    lines.push('');
  }

  if (operation.requestBody) {
    lines.push('## Request Body');
    lines.push('');
    lines.push('See schema in API reference UI.');
    lines.push('');
  }

  const responseCodes = Object.keys(operation.responses ?? {});
  if (responseCodes.length > 0) {
    lines.push('## Responses');
    lines.push('');
    for (const code of responseCodes) {
      const response = operation.responses[code];
      const description = (response?.description || '').replace(/\s+/g, ' ').trim();
      lines.push(`- \`${code}\`${description ? ` - ${description}` : ''}`);
    }
    lines.push('');
  }

  lines.push('## cURL');
  lines.push('');
  lines.push('```bash');
  lines.push(`curl -X ${method.toUpperCase()} "${defaultServerUrl}${routePath}" \\`);
  lines.push('  -H "Authorization: Bearer <token>" \\');
  lines.push('  -H "X-API-Key: <api-key>" \\');
  lines.push('  -H "Content-Type: application/json"');
  lines.push('```');
  lines.push('');

  for (const tag of tags) {
    const tagSlug = tagBySource.get(tag)?.slug ?? slugify(tag);
    artifacts.push({
      relPath: path.join(tagSlug, `${fileName}.md`),
      content: `${lines.join('\n')}\n`,
    });
  }
}

function collectParameters(parameters) {
  if (!Array.isArray(parameters)) return [];
  return parameters
    .map((item) => {
      if (!item || typeof item !== 'object' || '$ref' in item) return null;
      return item;
    })
    .filter(Boolean);
}

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function pruneComponents(doc) {
  const refsBySection = new Map();

  function addRef(ref) {
    if (typeof ref !== 'string' || !ref.startsWith('#/components/')) return false;
    const [, , section, ...nameParts] = ref.split('/');
    const name = decodeURIComponent(nameParts.join('/'));
    if (!section || !name) return false;
    const sectionSet = refsBySection.get(section) ?? new Set();
    const sizeBefore = sectionSet.size;
    sectionSet.add(name);
    refsBySection.set(section, sectionSet);
    return sectionSet.size > sizeBefore;
  }

  function collectRefs(value) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) {
      value.forEach(collectRefs);
      return;
    }
    if (typeof value.$ref === 'string') addRef(value.$ref);
    for (const child of Object.values(value)) collectRefs(child);
  }

  collectRefs(doc.paths);
  collectRefs(doc.webhooks);
  collectRefs(doc.components?.securitySchemes);
  collectRefs(doc.components?.parameters?.WorkspaceIdHeader);

  let changed = true;
  while (changed) {
    changed = false;
    for (const [section, names] of refsBySection.entries()) {
      const sectionObj = doc.components?.[section];
      if (!sectionObj) continue;
      for (const name of names) {
        const value = sectionObj[name];
        const before = countRefs(refsBySection);
        collectRefs(value);
        if (countRefs(refsBySection) > before) changed = true;
      }
    }
  }

  const nextComponents = {};
  for (const [section, names] of refsBySection.entries()) {
    const sectionObj = doc.components?.[section];
    if (!sectionObj) continue;
    const nextSection = {};
    for (const name of names) {
      if (sectionObj[name] !== undefined) nextSection[name] = sectionObj[name];
    }
    if (Object.keys(nextSection).length > 0) nextComponents[section] = nextSection;
  }

  if (doc.components?.securitySchemes) {
    nextComponents.securitySchemes = {
      ...(nextComponents.securitySchemes ?? {}),
      ...doc.components.securitySchemes,
    };
  }
  if (doc.components?.parameters?.WorkspaceIdHeader) {
    nextComponents.parameters = {
      ...(nextComponents.parameters ?? {}),
      WorkspaceIdHeader: doc.components.parameters.WorkspaceIdHeader,
    };
  }

  doc.components = nextComponents;
}

function countRefs(refsBySection) {
  let total = 0;
  for (const values of refsBySection.values()) total += values.size;
  return total;
}
