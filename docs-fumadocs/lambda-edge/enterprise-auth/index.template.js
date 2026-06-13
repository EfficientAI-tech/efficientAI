'use strict';

const crypto = require('crypto');

const PASSWORD_HASH = '{{PASSWORD_HASH}}';
const COOKIE_SECRET = '{{COOKIE_SECRET}}';
const SESSION_DAYS = 7;

const COOKIE_NAME = 'docs_ent';
const UNLOCK_PREFIX = '/docs/enterprise/unlock';
const ENTERPRISE_PREFIX = '/docs/enterprise/';

function timingSafeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i += 1) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function signSession(expiry) {
  return crypto.createHmac('sha256', COOKIE_SECRET).update(String(expiry)).digest('base64url');
}

function verifySession(value) {
  if (!value) return false;
  const separator = value.lastIndexOf('.');
  if (separator === -1) return false;

  const expiry = Number.parseInt(value.slice(0, separator), 10);
  const signature = value.slice(separator + 1);
  if (!Number.isFinite(expiry) || expiry < Date.now()) return false;

  const expected = signSession(expiry);
  return timingSafeEqual(signature, expected);
}

function parseCookies(headers) {
  const cookieHeader = headers.cookie;
  if (!cookieHeader) return {};

  const cookies = {};
  for (const item of cookieHeader) {
    const parts = item.value.split(';');
    for (const part of parts) {
      const trimmed = part.trim();
      const separator = trimmed.indexOf('=');
      if (separator === -1) continue;
      const key = trimmed.slice(0, separator);
      const value = trimmed.slice(separator + 1);
      cookies[key] = value;
    }
  }
  return cookies;
}

function parseFormBody(body, isBase64) {
  const raw = isBase64 ? Buffer.from(body, 'base64').toString('utf8') : body;
  const params = new URLSearchParams(raw);
  return {
    password: params.get('password') || '',
    returnTo: params.get('return') || '/docs/enterprise/overview/',
  };
}

function normalizeUri(uri) {
  return uri.endsWith('/') ? uri : `${uri}/`;
}

function isUnlockPath(uri) {
  return uri === '/docs/enterprise/unlock' || uri.startsWith('/docs/enterprise/unlock/');
}

function redirect(location, extraHeaders) {
  const response = {
    status: '302',
    statusDescription: 'Found',
    headers: {
      location: [{ key: 'Location', value: location }],
      'cache-control': [{ key: 'Cache-Control', value: 'no-store' }],
    },
  };

  if (extraHeaders) {
    Object.assign(response.headers, extraHeaders);
  }

  return response;
}

function passThrough(request) {
  return request;
}

exports.handler = async (event) => {
  const request = event.Records[0].cf.request;
  const uri = normalizeUri(request.uri);

  if (!uri.startsWith(ENTERPRISE_PREFIX)) {
    return passThrough(request);
  }

  if (isUnlockPath(uri)) {
    if (request.method === 'POST' && request.body && request.body.data) {
      const { password, returnTo } = parseFormBody(
        request.body.data,
        request.body.encoding === 'base64',
      );
      const submittedHash = sha256(password);

      if (!timingSafeEqual(submittedHash, PASSWORD_HASH)) {
        const errorTarget = `${UNLOCK_PREFIX}/?error=invalid&return=${encodeURIComponent(returnTo)}`;
        return redirect(errorTarget);
      }

      const expiry = Date.now() + SESSION_DAYS * 24 * 60 * 60 * 1000;
      const cookieValue = `${expiry}.${signSession(expiry)}`;
      const safeReturn = sanitizeReturnPath(returnTo);

      return redirect(safeReturn, {
        'set-cookie': [{
          key: 'Set-Cookie',
          value: `${COOKIE_NAME}=${cookieValue}; Path=/docs/enterprise/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_DAYS * 86400}`,
        }],
      });
    }

    return passThrough(request);
  }

  const cookies = parseCookies(request.headers);
  if (verifySession(cookies[COOKIE_NAME])) {
    return passThrough(request);
  }

  const returnTo = encodeURIComponent(uri);
  return redirect(`${UNLOCK_PREFIX}/?return=${returnTo}`);
};

function sanitizeReturnPath(value) {
  if (!value || !value.startsWith('/docs/enterprise/')) {
    return '/docs/enterprise/overview/';
  }
  if (isUnlockPath(value)) {
    return '/docs/enterprise/overview/';
  }
  return value.endsWith('/') ? value : `${value}/`;
}
