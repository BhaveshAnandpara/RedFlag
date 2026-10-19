// The rules a saved sample file must meet before it is shown to the public. The export script
// refuses to write a file that breaks them, and a test checks the committed file against them.

// Shapes of real keys, tokens and connection strings. The random fake "CANARY-" secrets that a
// leak test legitimately shows are not key-shaped and are allowed.
const KEY_SHAPES = [
  /gsk_[A-Za-z0-9]{10,}/,
  /AIza[A-Za-z0-9_-]{20,}/,
  /sk-or-[A-Za-z0-9-]{10,}/,
  /Bearer\s+[A-Za-z0-9._-]{10,}/,
  /postgres(?:ql)?(?:\+\w+)?:\/\//,
];

const VERDICTS = new Set(["pass", "fail", "inconclusive"]);
const JUDGE_STATES = new Set(["pass", "fail", "unavailable"]);

/**
 * Everything wrong with a sample file, as plain sentences. An empty list means it is fine.
 * A message never repeats the offending text, so a refused key is not printed anywhere.
 * @param {any} data
 * @returns {string[]}
 */
export function findProblems(data) {
  const problems = [];
  if (!data || data.format_version !== 1) {
    problems.push("The file is in the wrong format (expected format_version 1).");
  }
  if (!data || !Array.isArray(data.scans)) {
    problems.push("The scans must be a list.");
    return problems;
  }
  if (data.scans.length === 0) return problems; // shown as "No saved scans yet"

  const botOf = (scan) => scan?.scan?.bot_id;
  const weak = data.scans.filter((s) => botOf(s) === "acme-weak");
  const hardened = data.scans.filter((s) => botOf(s) === "acme-hardened");
  if (weak.length === 0) problems.push("There is no weak scan in the file.");
  if (hardened.length === 0) problems.push("There is no hardened scan in the file.");
  if (data.scans.length !== 2 || weak.length > 1 || hardened.length > 1) {
    problems.push("The file must hold exactly one weak scan and one hardened scan.");
  }

  for (const scan of data.scans) {
    const id = scan?.scan?.id;
    if (scan?.scan?.status !== "completed") {
      problems.push(`Scan #${id} is not completed (status: ${scan?.scan?.status}).`);
    }
    const results = Array.isArray(scan?.results) ? scan.results : [];
    if (results.length === 0) problems.push(`Scan #${id} has no results.`);
    for (const result of results) {
      if (!result.evidence) {
        problems.push(`Scan #${id}: the result for ${result.test_id} has no evidence.`);
      }
      if (VERDICTS.has(result.status) && (!result.model || !result.provider)) {
        problems.push(`Scan #${id}: the result for ${result.test_id} has a verdict but no model.`);
      }
      // The AI judge's fields are optional (scans from before the judge have none), but when
      // they are there they must be well shaped.
      const judge = result.judge_status;
      if (judge !== undefined && judge !== null) {
        if (!JUDGE_STATES.has(judge)) {
          problems.push(`Scan #${id}: the result for ${result.test_id} has an unknown judge status.`);
        } else {
          if (!result.judge_reason) {
            problems.push(`Scan #${id}: the judge reason for ${result.test_id} is missing.`);
          }
          if (judge !== "unavailable" && (!result.judge_model || !result.judge_provider)) {
            problems.push(`Scan #${id}: the judge verdict for ${result.test_id} has no model.`);
          }
        }
      }
    }
  }

  const text = JSON.stringify(data);
  if (KEY_SHAPES.some((shape) => shape.test(text))) {
    problems.push(
      "Something shaped like a key, token or connection string was found, so the file was refused.",
    );
  }
  return problems;
}
