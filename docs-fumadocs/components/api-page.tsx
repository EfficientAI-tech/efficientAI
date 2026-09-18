'use client';

import { createOpenAPIPage } from 'fumadocs-openapi/ui';
import { createCodeUsageGeneratorRegistry } from 'fumadocs-openapi/requests/generators';
import { registerDefault } from 'fumadocs-openapi/requests/generators/all';

const codeUsages = registerDefault(createCodeUsageGeneratorRegistry());
for (const languageId of ['java', 'csharp', 'rust']) codeUsages.remove(languageId);

export const OpenAPIPage = createOpenAPIPage({
  codeUsages,
  playground: { enabled: true },
});
