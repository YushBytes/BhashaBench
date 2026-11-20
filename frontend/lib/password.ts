/**
 * The server's rule for a new password (backend/app/auth/passwords.py,
 * `password_problem`), checked in the browser only so the form can say so
 * before sending. Length over composition rules, per NIST SP 800-63B. The
 * server checks again; `tests/password.test.mjs` fails if the bounds drift.
 */
export const MIN_PASSWORD_CHARS = 12;
export const MAX_PASSWORD_CHARS = 1024;

export function passwordProblem(password: string, email = ""): string | null {
  if (password.length < MIN_PASSWORD_CHARS) return `Use at least ${MIN_PASSWORD_CHARS} characters.`;
  if (password.length > MAX_PASSWORD_CHARS) return `Use at most ${MAX_PASSWORD_CHARS} characters.`;
  if (!password.trim()) return "A password cannot be only spaces.";
  if (email && password.toLowerCase() === email.toLowerCase()) return "Your password cannot be your email address.";
  return null;
}
