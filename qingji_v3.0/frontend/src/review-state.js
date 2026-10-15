// 服务端偏移按 Unicode 字符计算，避免 emoji 造成中文原句错位。
export function changedText(original, issues, choices) {
  let chars = Array.from(original);
  const edits = issues.filter((issue) => choices[issue.id] === "accepted" && issue.suggested_text)
    .sort((a, b) => b.start - a.start);
  let previousStart = chars.length + 1;
  for (const issue of edits) {
    if (issue.end > previousStart || chars.slice(issue.start, issue.end).join("") !== issue.quote) {
      throw new Error("修改位置发生变化，请先复查报告。");
    }
    chars.splice(issue.start, issue.end - issue.start, ...Array.from(issue.suggested_text));
    previousStart = issue.start;
  }
  return chars.join("");
}

export function highlightedLines(text, issues, choices, activeId) {
  const edits = issues.filter((issue) => choices[issue.id] === "accepted" && issue.suggested_text);
  const currentPositions = issues.filter((issue) => choices[issue.id] !== "accepted").map((issue) => {
    const shift = edits.filter((edit) => edit.end <= issue.start)
      .reduce((total, edit) => total + Array.from(edit.suggested_text).length - (edit.end - edit.start), 0);
    return {issue, start: issue.start + shift, end: issue.end + shift};
  });
  let offset = 0;
  return text.split("\n").map((line, index) => {
    const size = Array.from(line).length;
    const positions = [];
    for (const position of currentPositions) {
      const {issue} = position;
      const start = position.start - offset;
      const end = position.end - offset;
      if (start < 0 || end > size || Array.from(line).slice(start, end).join("") !== issue.quote) continue;
      positions.push({start, end, issue, active: issue.id === activeId});
    }
    const parts = [];
    let cursor = 0;
    for (const position of positions.sort((a, b) => a.start - b.start)) {
      if (position.start < cursor) continue;
      parts.push({text: Array.from(line).slice(cursor, position.start).join("")});
      parts.push({text: Array.from(line).slice(position.start, position.end).join(""), ...position});
      cursor = position.end;
    }
    parts.push({text: Array.from(line).slice(cursor).join("")});
    offset += size + 1;
    return {line, parts, key: index};
  });
}

export function downloadText(name, content, type = "text/plain;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
