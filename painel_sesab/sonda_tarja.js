const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const emMs=s=>{const m=(s||'').match(/(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
  return m?new Date(+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0)).getTime():null;};
const emMsISO=s=>{const m=(s||'').match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return m?new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime():null;};
function cenario(COLETA_EM, linhas){
  const REGUA=(()=>{const t=emMs(COLETA_EM); return t==null?Date.now():t;})();
  const reguaDe=d=>{const t=d&&emMsISO(d.medido_em); return t==null?REGUA:t;};
  const resumoEm=d=>{const m=(d&&d.resumo_em||'').match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m?new Date(+m[1],+m[2]-1,+m[3]).getTime():null;};
  const resumoAtrasado=d=>{const r=resumoEm(d); return r!=null&&r<reguaDe(d);};
  const resumoData=d=>{const m=(d&&d.resumo_em||'').match(/^(\d{4})-(\d{2})-(\d{2})/); return m?m[3]+'/'+m[2]:'';};
  const tarjaResumo=d=>{if(!d.resumo_em)return '';
    const dt=resumoData(d);
    return resumoAtrasado(d)
      ? `[VELHO] title="O resumo foi escrito sobre a coleta de ${esc(dt)}; este painel mostra a de ${esc(COLETA_EM)}."`
      : `[ok] descreve ${esc(dt)}`;};
  console.log('COLETA_EM =', COLETA_EM);
  for(const d of linhas) console.log('  medido_em', d.medido_em, '| resumo', d.resumo_em, '->', tarjaResumo(d));
}
// Carteira mista: bloco do poco de 15/08 (mais velho => define COLETA_EM) + linha lida hoje 18/08
cenario('15/08/2026 07:45',[
 {medido_em:'2026-08-18T07:45:16-03:00', resumo_em:'2026-08-18'},  // resumo da propria medicao de hoje
 {medido_em:'2026-08-18T07:45:16-03:00', resumo_em:'2026-08-13'},  // resumo genuinamente velho
 {medido_em:'2026-08-15T07:45:16-03:00', resumo_em:'2026-08-15'},  // linha do poco, resumo da sua medicao
]);
// Carteira homogenea (mundo pre-poco)
cenario('18/08/2026 07:45',[
 {medido_em:'2026-08-18T07:45:16-03:00', resumo_em:'2026-08-18'},
 {medido_em:'2026-08-18T07:45:16-03:00', resumo_em:'2026-08-13'},
]);
