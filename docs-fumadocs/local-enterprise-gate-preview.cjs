const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const { handler } = require('./lambda-edge/enterprise-auth/dist/index.js');

const PORT = Number.parseInt(process.env.PORT || '4173', 10);
const root = path.resolve(process.cwd(), 'out');

const contentTypes = {
  '.avif': 'image/avif',
  '.css': 'text/css; charset=utf-8',
  '.gif': 'image/gif',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

function resolveFile(urlPath) {
  const pathname = decodeURIComponent(urlPath.split('?')[0] || '/');
  const normalized = path.normalize(pathname).replace(/^(\.\.[/\\])+/, '');
  const candidates = [
    path.join(root, normalized),
    path.join(root, normalized, 'index.html'),
    path.join(root, `${normalized}.html`),
  ];

  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (!resolved.startsWith(root)) continue;
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
      return resolved;
    }
  }

  return null;
}

function toCloudFrontHeaders(headers) {
  const output = {};

  for (const [key, value] of Object.entries(headers)) {
    if (!value) continue;
    output[key.toLowerCase()] = [{ key, value: Array.isArray(value) ? value.join('; ') : String(value) }];
  }

  return output;
}

function sendLambdaResponse(res, result) {
  res.statusCode = Number(result.status);

  for (const values of Object.values(result.headers || {})) {
    for (const header of values) {
      res.setHeader(header.key, header.value);
    }
  }

  res.end(result.body || '');
}

function sendStaticFile(res, file) {
  res.setHeader('Content-Type', contentTypes[path.extname(file)] || 'application/octet-stream');
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer((req, res) => {
  const chunks = [];

  req.on('data', (chunk) => {
    chunks.push(chunk);
  });

  req.on('end', async () => {
    try {
      const [uri, querystring = ''] = (req.url || '/').split('?');
      const body = Buffer.concat(chunks).toString();

      const result = await handler({
        Records: [{
          cf: {
            request: {
              uri,
              querystring,
              method: req.method,
              headers: toCloudFrontHeaders(req.headers),
              ...(body ? { body: { encoding: 'text', data: body } } : {}),
            },
          },
        }],
      });

      if (result.status) {
        sendLambdaResponse(res, result);
        return;
      }

      const file = resolveFile(req.url || '/');
      if (!file) {
        res.statusCode = 404;
        res.setHeader('Content-Type', 'text/plain; charset=utf-8');
        res.end('Not found');
        return;
      }

      sendStaticFile(res, file);
    } catch (error) {
      res.statusCode = 500;
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      res.end(error instanceof Error ? error.stack : String(error));
    }
  });
});

server.listen(PORT, () => {
  console.log(`Enterprise docs gate preview: http://localhost:${PORT}/docs/enterprise/overview/`);
  console.log('Use the password from DOCS_ENTERPRISE_PASSWORD.');
});
