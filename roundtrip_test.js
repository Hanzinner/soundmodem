// РЕГРЕСІЯ: текст -> сигнал -> (+шум) -> декод -> байт-у-байт. Без мікрофона.
const fs=require('fs');
let script=fs.readFileSync(__dirname+'/web/dev.html','utf8').split('<script>')[1].split('</script>')[0];
const elP=new Proxy(function(){},{get:(t,k)=>{if(k==='classList')return{toggle(){},add(){},remove(){}};if(k==='style')return{};if(k==='textContent')return'';return elP;},set:()=>true,apply:()=>elP});
script+='\n;module.exports={makeBlocks,buildSignal,findPeaks,decodeChirp,ingestBlock,tryAssemble,resetRecv,setMode,cfg:()=>cfg(),getNCAR:()=>NCAR};';
const mod={exports:{}};
new Function('module','exports','document','fetch','window','TextEncoder','TextDecoder','Blob','URL','screen','navigator','setTimeout',script)
(mod,mod.exports,{getElementById:()=>elP,createElement:()=>elP,body:{appendChild(){},removeChild(){}}},()=>{},{},TextEncoder,TextDecoder,class{},{createObjectURL:()=>'',revokeObjectURL(){}},{width:0,height:0},{userAgent:'node'},f=>f&&f());
const M=mod.exports,SR=48000;
let seed=42;const rnd=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff;};
const gauss=()=>{let s=0;for(let i=0;i<6;i++)s+=rnd();return (s-3)/1.5;};
let pass=0,fail=0;
function trial(mode,len,noise){
  M.setMode(mode); M.resetRecv();
  const data=new Uint8Array(len);for(let i=0;i<len;i++)data[i]=(i*31+7)&255;
  const {blocks,nblk}=M.makeBlocks(data);
  const pcm=M.buildSignal(blocks,SR);
  const sig=new Float32Array(pcm.length);for(let i=0;i<pcm.length;i++)sig[i]=pcm[i]+gauss()*noise;
  const peaks=M.findPeaks(sig,SR);let got=0;
  for(const pk of peaks){const d=M.decodeChirp(sig,SR,pk.p);if(d&&d.ok&&M.ingestBlock(d))got++;}
  const asm=M.tryAssemble();
  const ok=asm&&!asm.bad&&asm.file.length===len&&Array.from(data).every((x,i)=>x===asm.file[i]);
  ok?pass++:fail++;
  console.log(`${mode.padEnd(5)} len=${String(len).padStart(5)} шум=${String(noise).padEnd(5)} -> ${nblk}блк, зловлено ${got}/${nblk}, ${(pcm.length/SR).toFixed(1)}с : ${ok?'OK':'ПРОВАЛ'}`);
}
console.log('=== РЕГРЕСІЯ round-trip ===');
trial('safe',9,0.01); trial('fast',9,0.01);
trial('safe',600,0.015); trial('fast',600,0.015);
trial('safe',2000,0.02); trial('safe',600,0.05); trial('safe',600,0.10);
console.log(`\n${pass} OK / ${fail} провалів`);
process.exit(fail?1:0);
