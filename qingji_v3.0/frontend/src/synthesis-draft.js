export function candidateBlock(project, result, group, item) {
  if(result.current===false||result.version!==project.version)throw new Error('分析对应旧版本，请重新生成。');
  const question=project.lifecycle.questions.find(q=>q.id===result.question_id);
  if(!question||!result.analysis[group]?.includes(item))throw new Error('请选择当前分析中的候选。');
  const labels={findings:'阶段理解',differences:'不同反馈',questions:'待了解事项'};
  const lines=[`【待核对的 AI 候选 · ${labels[group]}】`,question.text,item.text];
  for(const c of item.citations){
    const material=project.materials.find(m=>m.id===c.material_id);
    const observation=project.lifecycle.observations.find(o=>o.id===c.observation_id&&o.material_id===c.material_id&&o.question_id===question.id);
    if(!material||!material.enabled||material.consent_status!=='confirmed'||!observation)throw new Error('候选来源范围已变化，请重新生成。');
    lines.push(`来源：${material.name}（材料 ${material.id}；记录 ${observation.id}）`,`原文：${c.quote}`);
  }
  lines.push('适用限制：',...result.analysis.limits,'以上为候选理解，引用存在不等于结论成立。');
  return lines.join('\n');
}

export function appendCandidate(text,block) {
  const next=text+(text?'\n\n':'')+block;
  if(next.length>24000)throw new Error('加入后将超过报告编辑框的 24,000 字符上限，请先整理当前正文；不会截断内容。');
  return next;
}
