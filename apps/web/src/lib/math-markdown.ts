/** Normalize TeX delimiters without rewriting Markdown code examples. */
export function normalizeMathDelimiters(source: string): string {
  let output = "";
  let index = 0;
  let fence: { marker: string; length: number } | null = null;
  while (index < source.length) {
    const rest = source.slice(index);
    if (index === 0 || source[index - 1] === "\n") {
      const end = source.indexOf("\n", index);
      const line = source.slice(index, end < 0 ? source.length : end + 1);
      const marker = /^ {0,3}(`{3,}|~{3,})(.*)/.exec(line);
      if (fence) {
        if (marker && marker[1][0] === fence.marker && marker[1].length >= fence.length && !marker[2].trim()) fence = null;
        output += line;
        index += line.length;
        continue;
      }
      if (marker || /^( {4}|\t)/.test(line)) {
        if (marker) fence = { marker: marker[1][0], length: marker[1].length };
        output += line;
        index += line.length;
        continue;
      }
    }
    if (source[index] === "`") {
      const ticks = /^`+/.exec(rest)![0];
      const closing = new RegExp(`(?<!\u0060)${ticks}(?!\u0060)`, "g");
      closing.lastIndex = index + ticks.length;
      const match = closing.exec(source);
      const end = match ? match.index + ticks.length : index + ticks.length;
      output += source.slice(index, end);
      index = end;
      continue;
    }
    if (rest.startsWith("$$")) {
      const closing = source.indexOf("$$", index + 2);
      if (closing >= 0) {
        output += `\n$$\n${source.slice(index + 2, closing).trim()}\n$$\n`;
        index = closing + 2;
        continue;
      }
    }
    if (rest.startsWith("\\(") || rest.startsWith("\\[")) {
      const display = rest[1] === "[";
      const closing = source.indexOf(display ? "\\]" : "\\)", index + 2);
      if (closing >= 0) {
        const math = source.slice(index + 2, closing).trim();
        output += display ? `\n$$\n${math}\n$$\n` : `$${math}$`;
        index = closing + 2;
        continue;
      }
      // Preserve an unfinished streamed delimiter until its closing token arrives.
      output += `\\${source[index]}${source[index + 1]}`;
      index += 2;
      continue;
    }
    if (source[index] === "\\" && index + 1 < source.length) {
      output += source.slice(index, index + 2);
      index += 2;
      continue;
    }
    output += source[index++];
  }
  return output;
}
