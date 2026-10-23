"use client";

/**
 * Minimal auth client.
 *
 * Tokens live in localStorage. This is acceptable for this demo deployment
 * because the API is same-origin behind the Next.js rewrite; production
 * deployments should move refresh-token storage to an HttpOnly cookie
 * (see docs/reviews/engineering_audit.md - remaining risks).
 */

const ACCESS_KEY = "rag.access_token";
const REFRESH_KEY = "rag.refresh_token";

export interface Tokens {
  access_token: string;
  refresh_token: string;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function isLoggedIn(): boolean {
  return getAccessToken() !== null;
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

export async function login(email: string, password: string): Promise<Tokens> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (res.status === 401) {
    throw new Error("Invalid email or password");
  }
  if (res.status === 429) {
    throw new Error("Too many failed attempts. Please wait and try again.");
  }
  if (!res.ok) {
    throw new Error(`Login failed (${res.status})`);
  }
  const tokens = (await res.json()) as Tokens;
  window.localStorage.setItem(ACCESS_KEY, tokens.access_token);
  window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  return tokens;
}

export function logout(): void {
  clearTokens();
}
