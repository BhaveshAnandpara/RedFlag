import type { AttackRecord, Recordings, Run } from "@/lib/recordings";

const VERDICT_LABEL = { pass: "PASS", fail: "FAIL", inconclusive: "INCONCLUSIVE" } as const;

const BOTS = [
  { key: "weak", label: "Weak bot", blurb: "No protection added." },
  { key: "hardened", label: "Hardened bot", blurb: "Defenses switched on." },
] as const;

function RunPanel({ run, label, blurb }: { run: Run; label: string; blurb: string }) {
  return (
    <section aria-label={label} className="space-y-3 rounded border-2 p-4">
      <div>
        <h3 className="text-lg font-semibold">{label}</h3>
        <p className="text-sm">
          {blurb} Defenses on: {run.defenses.length > 0 ? run.defenses.join(", ") : "none"}.
        </p>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase">Reply</p>
        <p className="whitespace-pre-wrap">{run.reply || "(no reply)"}</p>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase">What the bot did (tool-call log)</p>
        {run.tool_calls.length === 0 ? (
          <p className="text-sm">No tools were called.</p>
        ) : (
          <ul aria-label="Tool calls" className="space-y-1 text-sm">
            {run.tool_calls.map((call, index) => (
              <li key={index} className="break-words">
                <span className="font-mono font-semibold">{call.tool}</span>{" "}
                <span className="font-mono">{JSON.stringify(call.arguments)}</span>
                {" → "}
                <span className="font-semibold">{call.outcome}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-1 rounded border-2 p-3">
        <p className="font-semibold">
          Verdict: <span>{VERDICT_LABEL[run.verdict.status]}</span>
        </p>
        <p className="text-sm">{run.verdict.evidence}</p>
        <p className="text-sm">
          <span className="font-semibold">How we decided:</span> {run.verdict.rule}
        </p>
      </div>

      <p className="text-xs">
        {run.model
          ? `Recorded on ${run.recorded_at.slice(0, 10)} with ${run.model}`
          : `Recorded on ${run.recorded_at.slice(0, 10)}. The model did not produce a result.`}
      </p>
    </section>
  );
}

function AttackCard({ attack }: { attack: AttackRecord }) {
  const headingId = `attack-${attack.id}`;
  return (
    <article aria-labelledby={headingId} className="space-y-4 rounded border-2 p-5">
      <header className="space-y-2">
        <h2 id={headingId} className="text-xl font-semibold">
          {attack.title}
        </h2>
        <p>
          <span className="font-semibold">What we are checking:</span> {attack.question}
        </p>
        <p>
          <span className="font-semibold">The attack message:</span>
        </p>
        <blockquote className="border-l-4 pl-3 italic">{attack.message}</blockquote>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        {BOTS.map(({ key, label, blurb }) => (
          <RunPanel key={key} run={attack.runs[key]} label={label} blurb={blurb} />
        ))}
      </div>
    </article>
  );
}

export function HowItWorks({ recordings }: { recordings: Recordings }) {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold">How Redflag tests your AI</h1>
        <p>
          Redflag sends your AI the kind of messages an attacker would, then checks the reply and
          everything the AI did, using simple facts and the rules you set. Here is that on two
          pretend support bots for a made-up shop. Both are given the same attacks.
        </p>
        <ul className="list-disc space-y-1 pl-6">
          <li>The weak bot has no protection. The hardened bot has defenses switched on.</li>
          <li>Every tool the bots use is pretend. It only writes a line in the log.</li>
          <li>All names, orders and codes are made up.</li>
        </ul>
        <p className="rounded border-2 p-3 text-sm">
          What you see below are recordings of real runs, saved as they happened and never edited.
          This page is not live: it asks no AI anything when you open it. A weak bot can still get
          lucky when a model refuses on its own, which is why a verdict always shows its evidence.
        </p>
      </header>
      {recordings.attacks.map((attack) => (
        <AttackCard key={attack.id} attack={attack} />
      ))}
    </div>
  );
}
