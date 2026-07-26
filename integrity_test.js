// ЦІЛІСНІСТЬ: сміття -> модем має ЗАВЖДИ впасти, НІКОЛИ не показати "дані".
// Міряємо на ТРЬОХ шарах: RS-ok (сирий) -> ingest (структура) -> assemble (CRC32 файлу = те що бачить юзер).
const fs=require('fs');
let script=fs.readFileSync(__dirname+'/web/dev.html','utf8').split('<script>')[1].split('</script>')[0];
const elP=new Proxy(function(){},{get:(t,k)=>{if(k==='classList')return{toggle(){},add(){},remove(){}};if(k==='style')return{};if(k==='textContent')return'';return elP;},set:()=>true,apply:()=>elP});
script+='\n;module.exports={findPeaks,decodeChirp,ingestBlock,tryAssemble,resetRecv,makeBlocks,buildSignal,setFREQS:(f)=>{FREQS=f.slice();GTX=f.map(()=>1);NCAR=f.length;},cfg:()=>cfg()};';
const mod={exports:{}};
new Function('module','exports','document','fetch','window','TextEncoder','TextDecoder','Blob','URL','screen','navigator','setTimeout',script)
(mod,mod.exports,{getElementById:()=>elP,createElement:()=>elP,body:{appendChild(){},removeChild(){}}},()=>{},{},TextEncoder,TextDecoder,class{},{createObjectURL:()=>'',revokeObjectURL(){}},{width:0,height:0},{userAgent:'node'},f=>f&&f());
const M=mod.exports,SR=48000;
let seed=20260726;const rnd=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff;};
const gauss=()=>{let s=0;for(let i=0;i<6;i++)s+=rnd();return (s-3)/1.5;};
const N=Math.round(SR*2.5);
const T={rs:0,ingest:0,output:0,correct:0,trials:0,chirps:0};
function feed(sig,expect){
  M.resetRecv();
  const peaks=M.findPeaks(sig,SR); T.chirps+=peaks.length; T.trials++;
  for(const pk of peaks){const d=M.decodeChirp(sig,SR,pk.p);if(d&&d.ok){T.rs++; if(M.ingestBlock(d))T.ingest++;}}
  const asm=M.tryAssemble();
  if(asm&&!asm.bad){
    const got=asm.file||null;
    if(!expect){T.output++;return;}                       // сміття на вході -> будь-який вивід = брехня
    const same=got&&got.length===expect.length&&Array.from(expect).every((x,i)=>x===got[i]);
    if(same)T.correct++; else T.output++;                 // збіглось = чесний успіх; ні = БРЕХНЯ
  }
}
function run(name,gen,reps){
  const b={...T};
  for(let r=0;r<reps;r++){const g=gen(r);Array.isArray(g)?feed(g[0],g[1]):feed(g);}
  const d={rs:T.rs-b.rs,ingest:T.ingest-b.ingest,output:T.output-b.output,ok:T.correct-b.correct,ch:T.chirps-b.chirps};
  console.log(`${name.padEnd(24)} проб=${String(reps).padStart(3)} чирпів=${String(d.ch).padStart(4)} | RS-ok=${String(d.rs).padStart(3)} ingest=${String(d.ingest).padStart(3)} вірно=${String(d.ok).padStart(3)} ХИБНИЙ-ВИВІД=${String(d.output).padStart(3)} ${d.output===0?'✓':'✗✗ SILENT-WRONG'}`);
}
console.log('=== ЦІЛІСНІСТЬ: сміття не має долізти до виводу ===');
run('білий шум',r=>{const s=new Float32Array(N);const amp=[0.01,0.05,0.2,0.6,1.0][r%5];for(let i=0;i<N;i++)s[i]=gauss()*amp;return s;},25);
run('тиша+кліки',r=>{const s=new Float32Array(N);for(let k=0;k<r%7;k++)s[Math.floor(rnd()*N)]=1;return s;},20);
run('музика',r=>{const s=new Float32Array(N);const f0=110*(1+r%6);for(let h=1;h<=10;h++)for(let i=0;i<N;i++)s[i]+=Math.sin(2*Math.PI*f0*h*i/SR+r)/h;for(let i=0;i<N;i++)s[i]*=0.2;return s;},15);
run('мова',r=>{const s=new Float32Array(N);for(let i=0;i<N;i++){const env=0.5+0.5*Math.sin(2*Math.PI*4*i/SR+r);s[i]=env*0.3*(Math.sin(2*Math.PI*(300+200*Math.sin(2*Math.PI*3*i/SR))*i/SR)+0.5*Math.sin(2*Math.PI*1800*i/SR));}return s;},15);
run('чужі свіпи',r=>{const s=new Float32Array(N);const f0=200+r*300,f1=f0+2000+r*500,D=Math.round(SR*(0.1+0.05*(r%4)));
  for(let st=0;st+D<N;st+=D+Math.round(SR*0.05)){const k=(f1-f0)/(D/SR);for(let i=0;i<D;i++){const t=i/SR;s[st+i]=0.5*Math.sin(2*Math.PI*(f0*t+0.5*k*t*t));}}return s;},18);
// НАЙЖОРСТКІШЕ: справжній сигнал, але покалічений (обрізаний / переставлений / з дірами)
run('справжній-покалічений',r=>{
  const data=new Uint8Array(120);for(let i=0;i<120;i++)data[i]=(i*7+r)&255;
  const {blocks}=M.makeBlocks(data);const pcm=M.buildSignal(blocks,SR);
  const s=Float32Array.from(pcm);
  const mode=r%4;
  if(mode===0){for(let i=Math.floor(s.length*0.4);i<s.length;i++)s[i]=0;}          // обрізаний
  else if(mode===1){for(let i=0;i<s.length;i++)if(rnd()<0.3)s[i]=gauss()*0.5;}      // діри-шум
  else if(mode===2){const h=s.length>>1;for(let i=0;i<h;i++){const t=s[i];s[i]=s[i+h];s[i+h]=t;}} // переставлений
  else {for(let i=0;i<s.length;i++)s[i]=s[i]*0.02+gauss()*0.4;}                     // втоплений у шум
  return [s,data];},24);
console.log('\n=== ПІДСУМОК ===');
console.log(`проб=${T.trials} чирпів=${T.chirps} | RS-ok=${T.rs} ingest=${T.ingest} | вірних=${T.correct} | ХИБНИХ ВИВОДІВ=${T.output}`);
console.log(T.output===0?'✓✓ ЦІЛІСНІСТЬ ТРИМАЄ (жодного разу не показав хибні дані)':'✗✗ ДІРКА — модем бреше');
