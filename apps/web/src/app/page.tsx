"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatInput } from "@/components/ChatInput";
import { ChatMessage } from "@/components/ChatMessage";
import { CitationList } from "@/components/CitationList";
import { getAccessToken, logout } from "@/lib/auth";

interface Citation {
  chunk_id: string;
  document_id: string;
  document_title: string;
  page: number | null;
  section: string | null;
  url: string | null;
  snippet: string;
  verified: boolean;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  trace_id?: string;
  confidence?: string;
  failure?: string | null;
}

interface QueryError {
  message: string;
  status: number | null;
}

export default function HomePage() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<QueryError | null>(null);
  const conversationIdRef = useRef<string | null>(null);

  // Auth gate: bounce to /login when there is no token.
  useEffect(() => {
    if (!getAccessToken()) {
      router.replace("/login");
    }
  }, [router]);

  const handleSend = useCallback(
    async (text: string) => {
      const token = getAccessToken();
      if (!token) {
        router.replace("/login");
        return;
      }
      setError(null);
      const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: text };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);

      try {
        const res = await fetch("/api/query", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            // THE fix: the bearer token was never attached before.
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            query: text,
            ...(conversationIdRef.current ? { conversation_id: conversationIdRef.current } : {}),
          }),
        });

        if (res.status === 401 || res.status === 403) {
          logout();
          router.replace("/login");
          return;
        }

        if (!res.ok) {
          // Server errors are surfaced as errors, never as assistant answers.
          setError({
            message:
              res.status === 422
                ? "The request was rejected by the server (validation)."
                : `Request failed with status ${res.status}.`,
            status: res.status,
          });
          return;
        }

        const data = await res.json();
        conversationIdRef.current = data.conversation_id ?? conversationIdRef.current;
        const assistantMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.answer,
          citations: data.citations,
          trace_id: data.trace_id,
          confidence: data.confidence,
          failure: data.failure,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        setError({
          message:
            err instanceof TypeError
              ? "Network error - is the API reachable?"
              : "Something went wrong. Please try again.",
          status: null,
        });
      } finally {
        setLoading(false);
      }
    },
    [router]
  );

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <main className="max-w-4xl mx-auto p-4">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Agentic RAG Platform</h1>
        <button
          onClick={handleLogout}
          className="rounded border border-gray-300 dark:border-gray-600 px-3 py-1 text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
        >
          Sign out
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded border border-red-300 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300"
        >
          {error.message}
          {error.status !== null && (
            <span className="ml-2 text-xs text-red-500">(HTTP {error.status})</span>
          )}
        </div>
      )}

      <div className="space-y-4 mb-4">
        {messages.map((m) => (
          <div key={m.id}>
            <ChatMessage message={m} />
            {m.citations && m.citations.length > 0 && <CitationList citations={m.citations} />}
          </div>
        ))}
        {loading && <div className="text-sm text-gray-500">Searching...</div>}
      </div>

      <ChatInput onSend={handleSend} disabled={loading} />
    </main>
  );
}
