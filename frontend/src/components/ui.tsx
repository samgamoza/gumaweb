"use client";

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-ink border border-line hover:bg-stone-50 disabled:opacity-50",
  ghost: "text-ink hover:bg-stone-100 disabled:opacity-50",
  danger: "bg-white text-red-700 border border-red-200 hover:bg-red-50 disabled:opacity-50",
};

export function Button({
  variant = "primary",
  size = "md",
  busy,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium transition-colors active:translate-y-px",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
    >
      {busy && <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cx("rounded-xl border border-line bg-white", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-4 border-b border-line px-5 py-3.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-xs text-stone-500">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm placeholder:text-stone-400 focus:border-brand-500 focus:outline-none";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const base = props.className?.match(/\bw-/) ? inputClass.replace("w-full ", "") : inputClass;
  return <input {...props} className={cx(base, "h-10", props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputClass, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  // Callers may set their own width; inputClass's w-full would otherwise win the cascade.
  const base = props.className?.match(/\bw-/) ? inputClass.replace("w-full ", "") : inputClass;
  return <select {...props} className={cx(base, "h-10", props.className)} />;
}

const TONES: Record<string, string> = {
  green: "bg-brand-50 text-brand-700 ring-brand-100",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  gray: "bg-stone-100 text-stone-700 ring-stone-200",
};

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  published: "green", approved: "green", claimed: "green", active: "green", succeeded: "green",
  completed: "green", generated: "blue", blueprint_ready: "blue", profiled: "blue", scored: "blue",
  pending_verification: "amber", manual_review: "amber", draft: "gray", discovered: "gray",
  unpublished: "gray", paused: "gray", archived: "gray", expired: "gray",
  failed: "red", rejected: "red",
};

export function Badge({ children, tone }: { children: ReactNode; tone?: keyof typeof TONES }) {
  const key = tone ?? STATUS_TONE[String(children)] ?? "gray";
  return (
    <span className={cx("inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[key])}>
      {typeof children === "string" ? children.replaceAll("_", " ") : children}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-stone-500">{hint}</div>}
    </div>
  );
}

export function Alert({ tone = "red", children }: { tone?: "red" | "green" | "amber"; children: ReactNode }) {
  if (!children) return null;
  const styles = { red: "border-red-200 bg-red-50 text-red-800", green: "border-brand-100 bg-brand-50 text-brand-900", amber: "border-amber-200 bg-amber-50 text-amber-900" };
  return <div role="status" className={cx("rounded-lg border px-3.5 py-2.5 text-sm", styles[tone])}>{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-4 py-10 text-center text-sm text-stone-500">{children}</div>;
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-stone-500">
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-2.5 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cx("px-3 py-2.5 align-middle", className)}>{children}</td>;
}

export function ScoreBar({ value }: { value: number | null }) {
  if (value === null) return <span className="text-stone-400">—</span>;
  const color = value >= 80 ? "bg-brand-500" : value >= 60 ? "bg-amber-400" : "bg-stone-300";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-stone-100">
        <div className={cx("h-full rounded-full", color)} style={{ width: `${value}%` }} />
      </div>
      <span className="tabular-nums text-stone-700">{value}</span>
    </div>
  );
}
