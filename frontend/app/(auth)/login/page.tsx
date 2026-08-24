"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { HOME_FOR_ROLE, useAuth } from "@/components/auth/AuthProvider";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { isApiError } from "@/lib/api";

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary to keep this route static.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  // Same destination the submit handler will use, so switching to Register
  // does not silently drop where the guard wanted to send them.
  const rawNext = searchParams.get("next");
  const safeNextHref =
    rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//")
      ? rawNext
      : null;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setFieldErrors({});

    try {
      const user = await login(email.trim(), password);

      // Honour a redirect the guard set, but only a same-origin path -- an
      // absolute URL here would be an open redirect.
      const next = searchParams.get("next");
      const safeNext = next && next.startsWith("/") && !next.startsWith("//")
        ? next
        : null;

      router.replace(safeNext ?? HOME_FOR_ROLE[user.role]);
    } catch (caught) {
      if (isApiError(caught)) {
        // Field-level messages where the server gave them; otherwise one
        // message above the form.
        const fields = caught.fieldErrors;
        if (fields.length > 0) {
          setFieldErrors(
            Object.fromEntries(fields.map((f) => [f.field, f.message])),
          );
        } else {
          setError(caught.message);
        }
      } else {
        setError("Something went wrong. Please try again.");
      }
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1 className="font-display text-3xl leading-tight tracking-tight text-text">
        Welcome back
      </h1>
      <p className="mt-2 text-sm text-muted">
        Sign in to book seats, manage shows, or run a venue.
      </p>

      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4" noValidate>
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-danger/25 bg-danger-soft px-3.5 py-3 text-[13px] text-danger"
          >
            {error}
          </div>
        )}

        <Input
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={fieldErrors.email}
          placeholder="you@example.com"
        />

        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={fieldErrors.password}
          placeholder="••••••••"
        />

        <Button type="submit" size="lg" loading={submitting} fullWidth className="mt-2">
          Sign in
        </Button>
      </form>

      <p className="mt-6 text-center text-[13px] text-muted">
        No account?{" "}
        <Link
          href={
            safeNextHref
              ? `/register?next=${encodeURIComponent(safeNextHref)}`
              : "/register"
          }
          className="text-text underline decoration-border underline-offset-4 transition-colors hover:decoration-accent"
        >
          Create one
        </Link>
      </p>
    </div>
  );
}
