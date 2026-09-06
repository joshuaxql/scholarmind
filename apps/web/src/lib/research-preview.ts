export interface DraftText { key: string; text: string }

// Read partial JSON strings without inventing closing JSON or accepting it as a
// valid report. Escaped quotes, newlines, and unfinished Unicode escapes survive
// arbitrary token boundaries. Only user-facing text fields are displayed.
export function researchPreview(source: string, planning = false): DraftText[] {
  const allowed = new Set(planning ? ["terms"] : [
    "overview", "methodology", "name", "summary", "period", "development",
    "title", "description", "rationale",
  ]);
  const result: DraftText[] = [];
  let key = "";
  const containers: string[] = [];
  let previous = "";
  for (let i = 0; i < source.length; i++) {
    const character = source[i];
    if (character === "{" || character === "[") containers.push(character);
    if (character === "}" || character === "]") containers.pop();
    if (character !== '"') {
      if (character.trim()) previous = character;
      continue;
    }
    const isKey = containers.at(-1) === "{" && previous !== ":";
    let text = "";
    let complete = false;
    for (i++; i < source.length; i++) {
      const ch = source[i];
      if (ch === '"') { complete = true; break; }
      if (ch !== "\\") { text += ch; continue; }
      const escaped = source[++i];
      if (escaped === undefined) break;
      if (escaped === "u") {
        const hex = source.slice(i + 1, i + 5);
        if (!/^[\da-f]{4}$/i.test(hex)) break;
        text += String.fromCharCode(parseInt(hex, 16));
        i += 4;
      } else {
        const escapes: Record<string, string> = { n: "\n", r: "\r", t: "\t", b: "\b", f: "\f", '"': '"', "\\": "\\", "/": "/" };
        text += escapes[escaped] ?? "";
      }
    }
    if (isKey) { if (complete) key = text; }
    else if (allowed.has(key) && text) result.push({ key, text });
    previous = '"';
  }
  return result;
}
