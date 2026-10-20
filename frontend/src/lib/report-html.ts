// A print-friendly page for the Markdown report, so it can be printed or saved as a PDF.
//
// It reads only the small part of Markdown the report uses (headings, paragraphs, bold, code,
// lists with one level of nesting, tables and rules). Everything is escaped first, so anything a
// bot said that looks like HTML is text on the page and never runs in the print window.

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

const escape = (text: string) => text.replace(/[&<>"']/g, (c) => ESCAPES[c]);

function inline(text: string): string {
  return escape(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function cells(line: string): string[] {
  // A bar written as \| inside a cell belongs to the cell.
  const parts = line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split(/(?<!\\)\|/);
  return parts.map((part) => part.trim().replace(/\\\|/g, "|"));
}

const STYLE = `
  body { font: 14px/1.5 Arial, Helvetica, sans-serif; color: #111; max-width: 780px; margin: 24px auto; padding: 0 16px; }
  h1 { font-size: 24px; } h2 { font-size: 18px; margin-top: 28px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
  h3 { font-size: 15px; margin-top: 18px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #bbb; padding: 4px 8px; text-align: left; vertical-align: top; }
  th { background: #eee; } code { background: #f1f1f1; padding: 0 3px; }
  hr { margin: 24px 0; } li { margin: 2px 0; }
  @media print { body { margin: 0; max-width: none; } h2, h3 { break-after: avoid; } tr, li { break-inside: avoid; } }
`;

export function reportHtml(markdown: string, title: string): string {
  const lines = markdown.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i += 1;
    } else if (/^---+$/.test(line.trim())) {
      out.push("<hr>");
      i += 1;
    } else if (/^#{1,3} /.test(line)) {
      const level = line.indexOf(" ");
      out.push(`<h${level}>${inline(line.slice(level + 1))}</h${level}>`);
      i += 1;
    } else if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[\s|:-]+\|$/.test(lines[i].trim())) rows.push(cells(lines[i]));
        i += 1;
      }
      const [head, ...body] = rows;
      out.push(
        "<table><thead><tr>" +
          head.map((c) => `<th>${inline(c)}</th>`).join("") +
          "</tr></thead><tbody>" +
          body.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
          "</tbody></table>",
      );
    } else if (/^\s*- /.test(line)) {
      const items: { text: string; children: string[] }[] = [];
      while (i < lines.length && /^\s*- /.test(lines[i])) {
        const nested = lines[i].startsWith("  ");
        const text = lines[i].replace(/^\s*- /, "");
        if (nested && items.length > 0) items[items.length - 1].children.push(text);
        else items.push({ text, children: [] });
        i += 1;
      }
      out.push(
        "<ul>" +
          items
            .map(
              (item) =>
                `<li>${inline(item.text)}` +
                (item.children.length > 0
                  ? "\n<ul>\n" + item.children.map((c) => `<li>${inline(c)}</li>`).join("\n") + "\n</ul>\n"
                  : "") +
                "</li>",
            )
            .join("") +
          "</ul>",
      );
    } else {
      const paragraph: string[] = [];
      while (
        i < lines.length &&
        lines[i].trim() !== "" &&
        !/^(#{1,3} |---+$|\||\s*- )/.test(lines[i].trim() === lines[i] ? lines[i] : lines[i])
      ) {
        paragraph.push(lines[i]);
        i += 1;
      }
      out.push(`<p>${inline(paragraph.join(" "))}</p>`);
    }
  }
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${escape(title)}</title><style>${STYLE}</style></head><body>${out.join("\n")}</body></html>`;
}
