// 仅比较作者可编辑的字段；版本号和历史由服务端维护。
export function editableProjectState(project) {
  return {choices:project.choices,manual_text:project.manual_text,
    reading_size:project.reading_size,materials:project.materials};
}

function ordered(value) {
  if (Array.isArray(value)) return value.map(ordered);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(k=>[k,ordered(value[k])]));
  return value;
}

export function changedProjectFields(project, requested) {
  return Object.fromEntries(Object.entries(requested).filter(([key,value])=>
    JSON.stringify(ordered(value))!==JSON.stringify(ordered(project[key]))));
}
