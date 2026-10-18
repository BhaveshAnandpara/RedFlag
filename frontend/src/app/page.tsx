import Link from "next/link";

import { HealthStatus } from "@/components/health-status";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-4xl font-semibold tracking-tight">Redflag</h1>
        <p className="text-lg text-zinc-700 dark:text-zinc-300">
          A final security check for AI apps before you release them.
        </p>
      </header>
      <p>
        <Link href="/how-it-works" className="font-medium underline underline-offset-4">
          See how Redflag tests an AI
        </Link>
      </p>
      <HealthStatus apiUrl={apiUrl} />
    </main>
  );
}
