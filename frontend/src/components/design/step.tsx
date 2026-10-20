import type { ReactNode } from "react";

export type StepState = "active" | "done" | "locked";

/**
 * One step of the rail. Only the active step shows its body; a finished step shows a one-line
 * summary and a Change link. Everything the person typed lives in the page, so a step can close and
 * open again without losing it.
 */
export function Step({
  n,
  id,
  title,
  state,
  summary,
  onChange,
  children,
}: {
  n: number;
  id: string;
  title: string;
  state: StepState;
  summary?: string;
  onChange?: () => void;
  children?: ReactNode;
}) {
  return (
    <section className={`step ${state}`} id={id} aria-labelledby={`${id}h`}>
      <span className="dot">{n}</span>
      <div className="step-head">
        <h2 id={`${id}h`}>{title}</h2>
        {state === "done" && summary && <span className="sum">{summary}</span>}
        {state === "done" && onChange && (
          <button type="button" className="edit" onClick={onChange}>
            Change
          </button>
        )}
      </div>
      {state === "active" && <div className="body">{children}</div>}
    </section>
  );
}
