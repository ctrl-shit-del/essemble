"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { HOME_FOR_ROLE, useAuth } from "@/components/auth/AuthProvider";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { isApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

type SelfServiceRole = "customer" | "organiser";

const ROLES: { value: SelfServiceRole; label: string; blurb: string }[] = [
  { value: "customer", label: "Book tickets", blurb: "Browse and book seats." },
  {
    value: "organiser",
    label: "List events",
    blurb: "Schedule shows at venues.",
  },
];

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();

  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [role, setRole] = useState<SelfServiceRole>("customer");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  function update(key: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [key]: event.target.value }));
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setFieldErrors({});

    try {
      const user = await register({
        name: form.name.trim(),
        email: form.email.trim(),
        password: form.password,
        role,
      });
      router.replace(HOME_FOR_ROLE[user.role]);
    } catch (caught) {
      if (isApiError(caught)) {
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
        Create an account
      </h1>
      <p className="mt-2 text-sm text-muted">
        Takes a moment. No card required.
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

        {/* Admin is absent by design: the API refuses role='admin' on
            register, so offering it would be an option that always fails. */}
        <fieldset>
          <legend className="mb-1.5 text-[13px] font-medium text-muted">
            I want to
          </legend>
          <div className="grid grid-cols-2 gap-2">
            {ROLES.map((option) => {
              const selected = role === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setRole(option.value)}
                  aria-pressed={selected}
                  className={cn(
                    "rounded-lg border px-3.5 py-3 text-left transition-colors duration-150",
                    selected
                      ? "border-accent bg-accent-soft"
                      : "border-border bg-surface hover:border-border-strong",
                  )}
                >
                  <span
                    className={cn(
                      "block text-sm font-medium",
                      selected ? "text-accent" : "text-text",
                    )}
                  >
                    {option.label}
                  </span>
                  <span className="mt-0.5 block text-[12px] leading-snug text-muted">
                    {option.blurb}
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>

        <Input
          label="Name"
          name="name"
          autoComplete="name"
          required
          value={form.name}
          onChange={update("name")}
          error={fieldErrors.name}
          placeholder="Rohan Desai"
        />

        <Input
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update("email")}
          error={fieldErrors.email}
          placeholder="you@example.com"
        />

        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="new-password"
          required
          minLength={8}
          value={form.password}
          onChange={update("password")}
          error={fieldErrors.password}
          hint="At least 8 characters."
          placeholder="••••••••"
        />

        <Button type="submit" size="lg" loading={submitting} fullWidth className="mt-2">
          Create account
        </Button>
      </form>

      <p className="mt-6 text-center text-[13px] text-muted">
        Already have one?{" "}
        <Link
          href="/login"
          className="text-text underline decoration-border underline-offset-4 transition-colors hover:decoration-accent"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}
