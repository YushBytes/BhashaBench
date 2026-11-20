/**
 * The Content-Security-Policy for every page, built per request around a nonce.
 *
 * Pure so it can be unit-tested without a server (`tests/csp.test.mjs`); the
 * proxy (`proxy.ts`) mints the nonce and sets the header. Next reads the
 * nonce back out of the request's CSP header and stamps it on every script
 * and style tag it renders, including the bootstrap and streaming scripts.
 *
 * Every relaxation is listed with its reason, because an unexplained
 * exception is how a policy decays into decoration:
 *
 * - `'strict-dynamic'`: scripts a nonced script loads (Next's chunks) are
 *   trusted without listing each. Host allowlists are then ignored by
 *   CSP3 browsers, which is the point.
 * - `style-src-attr 'unsafe-inline'`: React `style={...}` attributes (chart
 *   bar widths, the audio progress bar) are inline style *attributes*, which
 *   a nonce cannot cover. Attributes cannot run script; `<style>` elements
 *   still need the nonce.
 * - `'unsafe-eval'` in development only: React's dev build uses `eval` to
 *   rebuild server error stacks. Never in production.
 * - `connect-src 'self'`: the browser calls only this origin (`/api/v1` is
 *   proxied to the backend), and CSP3's `'self'` also matches same-origin
 *   `ws:`/`wss:`, which the dev server's hot reload uses.
 * - `img-src`/`media-src` `blob: data:`: decoded audio and generated
 *   downloads are blob URLs; icons may be data URLs.
 */

export function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function contentSecurityPolicy(nonce: string, { dev = false }: { dev?: boolean } = {}): string {
  if (!/^[A-Za-z0-9+/]{22}==$/.test(nonce)) throw new Error("a CSP nonce must be 16 random bytes, base64-encoded");
  const directives: [string, string[]][] = [
    ["default-src", ["'self'"]],
    ["script-src", ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(dev ? ["'unsafe-eval'"] : [])]],
    ["style-src", ["'self'", `'nonce-${nonce}'`]],
    ["style-src-attr", ["'unsafe-inline'"]],
    ["img-src", ["'self'", "blob:", "data:"]],
    ["media-src", ["'self'", "blob:"]],
    ["font-src", ["'self'"]],
    ["connect-src", ["'self'"]],
    ["worker-src", ["'self'", "blob:"]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
    ["frame-ancestors", ["'none'"]],
  ];
  return directives.map(([name, sources]) => `${name} ${sources.join(" ")}`).join("; ");
}
