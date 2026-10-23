"use client";

/**
 * Auth client.
 *
 * Token model (matches the backend's hardened auth):
 * - The ACCESS token (short-lived) lives in sessionStorage - readable by JS,
 *   but it expires quickly and is not the long-lived credential.
 * - The REFRESH token lives ONLY in an HttpOnly cookie set by the server.
 *   JavaScript never sees it; refresh/logout calls rely on the browser
 *   attaching the cookie automatically (same-origin /api rewrite).
 * - refreshAccessToken() performs a silent refresh (cookie -> new access
 *   token). Each refresh token is single-use (server-side rotation).
 */

const ACCESS_KEY = "rag.access_token";

export interface Tokens {
  access_token: string;
  refresh_token: string; // present for API clients; the browser ignores it
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(ACCESS_KEY);
}

function setAccessToken(token: string): void {
  window.sessionStorage.setItem(ACCESS_KEY, token);
}

export function isLoggedIn(): boolean {
  return getAccessToken() !== null;
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(ACCESS_KEY);
}

export async function login(email: string, password: string): Promise<Tokens> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "include", // receive the HttpOnly refresh cookie
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
  // Only the access token is stored client-side. The refresh token stays
  // in the HttpOnly cookie the server just set.
  setAccessToken(tokens.access_token);
  return tokens;
}

/**
 * Silent refresh: ask the server for a new access token. The refresh token
 * is sent automatically via the HttpOnly cookie. Returns null when the
 * session is gone (expired/revoked) and the user must log in again.
 */
export async function refreshAccessToken(): Promise<string | null> {
  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { access_token?: string };
    if (!data.access_token) return null;
    setAccessToken(data.access_token);
    return data.access_token;
  } catch {
    return null;
  }
}

/**
 * Logout: revoke the refresh token server-side (the cookie carries it) and
 * clear the local access token. Safe to call when already signed out.
 */
export async function logout(): Promise<void> {
  clearTokens();
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Network failures must not block local sign-out.
  }
}
