import { createOpenAPI } from 'fumadocs-openapi/server';
import { join } from 'node:path';

export const openapi = createOpenAPI({
  input: { efficientai: join(process.cwd(), 'openapi', 'efficientai.json') },
});
