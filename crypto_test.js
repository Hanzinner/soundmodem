// КРИПТО end-to-end: текст -> AES-GCM -> звук -> декод -> дешифр. Невірний пароль МУСИТЬ впасти.
const fs=require('fs');
const {webcrypto}=require('crypto');
let script=fs.readFileSync(__dirname+'/web/dev.html','utf8').split('<script>')[1].split('</script>')[0];
const elP=new Proxy(function(){},{get:(t,k)=>{if(k==='classList')return{toggle(){},add(){},remove(){}};if(k==='style')return{};if(k==='textContent')return'';if(k==='value')return'';return elP;},set:()=>true,apply:()=>elP});
script+='\n;module.exports={setIter:(n)=>{KDF_ITER=n;},encryptBytes,decryptBytes,isEncrypted,makeBlocks,buildSignal,findPeaks,decodeChirp,ingestBlock,tryAssemble,resetRecv,setMode};';
const mod={exports:{}};
new Function('module','exports','document','fetch','window','TextEncoder','TextDecoder','Blob','URL','screen','navigator','setTimeout','crypto',script)
(mod,mod.exports,{getElementById:()=>elP,createElement:()=>elP,body:{appendChild(){},removeChild(){}}},()=>{},{},TextEncoder,TextDecoder,class{},{createObjectURL:()=>'',revokeObjectURL(){}},{width:0,height:0},{userAgent:'node'},f=>f&&f(),webcrypto);
const M=mod.exports,SR=48000;
(async()=>{
  const secret='abandon ability able about above absent absorb abstract absurd abuse access accident';
  const pass='кодова фраза яку я тримаю в голові';
  const data=new TextEncoder().encode(secret);
  console.log('секрет:',data.length,'B');
  const enc=await M.encryptBytes(data,pass);
  console.log('зашифровано:',enc.length,'B (оверхед',enc.length-data.length,'B) | магія HSC1:',M.isEncrypted(enc));
  // через модем
  M.setMode('safe');M.resetRecv();
  const {blocks,nblk}=M.makeBlocks(enc);
  const pcm=M.buildSignal(blocks,SR);
  console.log('звук:',(pcm.length/SR).toFixed(1),'с,',nblk,'блоків');
  const peaks=M.findPeaks(pcm,SR);let got=0;
  for(const pk of peaks){const d=M.decodeChirp(pcm,SR,pk.p);if(d&&d.ok&&M.ingestBlock(d))got++;}
  const asm=M.tryAssemble();
  if(!asm||asm.bad){console.log('✗ модем не зібрав');process.exit(1);}
  console.log('модем зібрав:',asm.file.length,'B | зашифроване?',M.isEncrypted(asm.file));
  const plain=await M.decryptBytes(asm.file,pass);
  const txt=new TextDecoder().decode(plain);
  console.log('розшифровано:',txt===secret?'✓ ІДЕНТИЧНО':'✗ НЕ ЗБІГЛОСЬ');
  // невірний пароль
  let rejected=false;
  try{await M.decryptBytes(asm.file,pass+'x');}catch(e){rejected=true;}
  console.log('невірний пароль:',rejected?'✓ ВІДХИЛЕНО':'✗✗ ПРОЙШОВ — ДІРКА');
  // підробка (змінили байт шифротексту) — GCM має спіймати
  const tamp=Uint8Array.from(asm.file);tamp[40]^=1;
  let caught=false;
  try{await M.decryptBytes(tamp,pass);}catch(e){caught=true;}
  console.log('підробка байта:',caught?'✓ СПІЙМАНО (GCM автентифікація)':'✗✗ ПРОПУЩЕНО');
  // різні рівні міцності: приймач має взяти число перемелів із заголовка
  let allOk=true;
  for(const it of [200000,2000000]){
    M.setIter(it);
    const e2=await M.encryptBytes(data,pass);
    M.setIter(600000);                       // приймач НЕ знає що обрав відправник
    const t0=Date.now(); let ok2=false;
    try{const p2=await M.decryptBytes(e2,pass);ok2=new TextDecoder().decode(p2)===secret;}catch(e){}
    console.log(`міцність ${(it/1000)|0}k -> розшифровано іншим налаштуванням: ${ok2?'✓':'✗ ПРОВАЛ'} (${Date.now()-t0}ms)`);
    allOk=allOk&&ok2;
  }
  process.exit(txt===secret&&rejected&&caught&&allOk?0:1);
})();
