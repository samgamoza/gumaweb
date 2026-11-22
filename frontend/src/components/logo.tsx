import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 font-semibold tracking-tight">
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true">
        <rect width="24" height="24" rx="6" className="fill-brand-600" />
        <path d="M7 8.5h10M7 12h6M7 15.5h8" stroke="white" strokeWidth="2" strokeLinecap="round" />
      </svg>
      GumaWeb
    </Link>
  );
}
