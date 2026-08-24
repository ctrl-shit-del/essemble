"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { OptionCards } from "./OptionCards";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/components/auth/AuthProvider";
import { isApiError } from "@/lib/api";
import {
  EXAMPLE_PROMPTS,
  clearConversation,
  describeTools,
  loadConversation,
  saveConversation,
  sendMessage,
  type ChatMessage,
} from "@/lib/assistant";
import { cn } from "@/lib/cn";

/**
 * The assistant panel.
 *
 * Customer-only, and mounted only by the customer layout -- an organiser or
 * an admin has no booking to make, so the control does not exist for them
 * rather than existing and refusing.
 */
export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [rateLimited, setRateLimited] = useState<string | null>(null);

  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setMessages(loadConversation());
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (messages.length > 0) saveConversation(messages);
  }, [messages]);

  // Clearing on logout, not just on close: the next person to use this
  // browser is not necessarily the person who asked the questions.
  useEffect(() => {
    if (!user) {
      clearConversation();
      setMessages([]);
    }
  }, [user]);

  useEffect(() => {
    listRef.current?.scrollTo({
      top: listRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, sending]);

  const send = useCallback(
    async (text: string) => {
      const body = text.trim();
      if (!body || sending) return;

      setDraft("");
      setRateLimited(null);
      const outgoing: ChatMessage = {
        id: `u-${Date.now()}`,
        role: "user",
        content: body,
      };
      // Snapshot BEFORE appending: the server wants the history that led up
      // to this message, not the message itself twice.
      const history = messages.map(({ role, content }) => ({ role, content }));
      setMessages((current) => [...current, outgoing]);
      setSending(true);

      try {
        const result = await sendMessage(body, history);
        setMessages((current) => [
          ...current,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: result.reply,
            options: result.options,
            tools: result.tool_calls_made,
          },
        ]);
      } catch (error) {
        if (isApiError(error) && error.status === 503) {
          setUnavailable(
            "The assistant isn't available right now. You can still browse and book normally.",
          );
        } else if (isApiError(error) && error.status === 429) {
          const details = error.details as { retry_after_seconds?: number } | null;
          const seconds = details?.retry_after_seconds ?? 3600;
          const minutes = Math.max(1, Math.ceil(seconds / 60));
          setRateLimited(
            `You've reached the hourly limit. Try again in about ${minutes} ${
              minutes === 1 ? "minute" : "minutes"
            }.`,
          );
        } else {
          setMessages((current) => [
            ...current,
            {
              id: `e-${Date.now()}`,
              role: "assistant",
              content: isApiError(error)
                ? error.message
                : "Something went wrong. Try asking again.",
            },
          ]);
        }
      } finally {
        setSending(false);
        inputRef.current?.focus();
      }
    },
    [messages, sending],
  );

  const empty = messages.length === 0;

  return (
    <div
      role="dialog"
      aria-label="ESSEMBLE Assistant"
      className={cn(
        "glass flex h-[min(34rem,70vh)] w-[min(24rem,calc(100vw-2rem))] flex-col",
        "overflow-hidden rounded-2xl shadow-2xl",
        "animate-[essemble-fade-in_180ms_var(--ease-out-soft)]",
      )}
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <SparkIcon className="h-4 w-4 text-accent" />
          <p className="font-display text-[15px] text-text">
            ESSEMBLE Assistant
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close assistant"
          className="grid h-7 w-7 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-text"
        >
          <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
            <path
              d="M2 2l8 8M10 2L2 10"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </header>

      <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-4">
        {unavailable ? (
          <div className="rounded-xl border border-border bg-surface p-4 text-center">
            <p className="text-[13px] leading-relaxed text-text">{unavailable}</p>
          </div>
        ) : empty ? (
          <div>
            <p className="text-[13px] leading-relaxed text-muted">
              Tell me what you feel like watching and I&rsquo;ll find seats
              worth booking. I can&rsquo;t book them for you &mdash; you tap
              the one you want.
            </p>
            <ul className="mt-4 space-y-2">
              {EXAMPLE_PROMPTS.map((prompt) => (
                <li key={prompt}>
                  <button
                    type="button"
                    onClick={() => void send(prompt)}
                    className="w-full rounded-lg border border-border bg-surface px-3.5 py-2.5 text-left text-[13px] text-text transition-colors hover:border-accent hover:bg-surface-2"
                  >
                    {prompt}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <ul className="space-y-4">
            {messages.map((message) => (
              <li
                key={message.id}
                className={cn(
                  "flex",
                  message.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    message.role === "user"
                      ? "max-w-[85%] rounded-2xl rounded-br-sm bg-surface-2 px-3.5 py-2.5"
                      : "w-full",
                  )}
                >
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-text">
                    {message.content}
                  </p>

                  {message.options && message.options.length > 0 && (
                    <OptionCards options={message.options} />
                  )}

                  {/* Legible rather than magical: say what actually ran. */}
                  {message.tools && message.tools.length > 0 && (
                    <p className="mt-2 text-[11px] text-muted">
                      {describeTools(message.tools)}
                    </p>
                  )}
                </div>
              </li>
            ))}

            {sending && (
              <li className="flex justify-start">
                <span className="flex items-center gap-1 px-1 py-2" aria-label="Thinking">
                  {[0, 1, 2].map((dot) => (
                    <span
                      key={dot}
                      className="h-1.5 w-1.5 rounded-full bg-muted animate-[essemble-pulse-soft_1.2s_ease-in-out_infinite]"
                      style={{ animationDelay: `${dot * 0.18}s` }}
                    />
                  ))}
                </span>
              </li>
            )}
          </ul>
        )}

        {rateLimited && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-danger/25 bg-danger-soft px-3.5 py-3 text-[12px] leading-relaxed text-danger"
          >
            {rateLimited}
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
        className="border-t border-border p-3"
      >
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter is a newline -- the convention
              // everyone already has in their fingers.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(draft);
              }
            }}
            rows={1}
            disabled={Boolean(unavailable)}
            placeholder="Two seats tonight…"
            aria-label="Message the assistant"
            className="max-h-24 min-h-[2.5rem] flex-1 resize-none rounded-lg border border-border bg-surface px-3 py-2.5 text-[13px] text-text outline-none transition-colors placeholder:text-muted/60 focus:border-accent disabled:opacity-50"
          />
          <Button
            type="submit"
            size="sm"
            loading={sending}
            disabled={!draft.trim() || Boolean(unavailable)}
          >
            Send
          </Button>
        </div>
        {!empty && !unavailable && (
          <button
            type="button"
            onClick={() => {
              clearConversation();
              setMessages([]);
              setRateLimited(null);
            }}
            className="mt-2 text-[11px] text-muted transition-colors hover:text-text"
          >
            Start over
          </button>
        )}
      </form>
    </div>
  );
}

export function SparkIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden="true">
      <path
        d="M8 1.5l1.5 4L13.5 7l-4 1.5L8 12.5 6.5 8.5 2.5 7l4-1.5z"
        fill="currentColor"
      />
      <path d="M12.75 11l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6z" fill="currentColor" />
    </svg>
  );
}
