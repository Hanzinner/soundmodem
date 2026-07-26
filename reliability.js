// Reliability scorer: проганяє ПОТОЧНИЙ декод (dual-detector+самонавчання) проти реального запису+meta+істини.
// node reliability.js <recording.pcm16> <meta.json> <groundtruth.txt>
const fs=require('fs');
let script=fs.readFileSync(__dirname+'/web/dev.html','utf8').split('<script>')[1].split('</script>')[0];
const elP=new Proxy(function(){},{get:(t,k)=>{if(k==='classList')return{toggle(){},add(){},remove(){}};if(k==='style')return{};if(k==='textContent')return'';return elP;},set:()=>true,apply:()=>elP});
script+='\n;module.exports={makeBlocks,bytesToBits,findPeaks,decodeChirp,decodeChirpBits,learnFrom,dropBadCarriers,setFREQS:(f)=>{FREQS=f.slice();GTX=f.map(()=>1);NCAR=f.length;},getNCAR:()=>NCAR,cfg:()=>cfg(),clearLearn:()=>learnMap.clear()};';
const mod={exports:{}};
new Function('module','exports','document','fetch','window','TextEncoder','TextDecoder','Blob','URL','screen','navigator','setTimeout',script)
(mod,mod.exports,{getElementById:()=>elP,createElement:()=>elP,body:{appendChild(){},removeChild(){}}},()=>{},{},TextEncoder,TextDecoder,class{},{createObjectURL:()=>'',revokeObjectURL(){}},{width:0,height:0},{userAgent:'node'},f=>f&&f());
const M=mod.exports,SR=48000;
const meta=JSON.parse(fs.readFileSync(process.argv[3]));M.setFREQS(meta.FREQS);
const buf=fs.readFileSync(process.argv[2]);const i16=new Int16Array(buf.buffer,buf.byteOffset,buf.length/2);const rec=new Float32Array(i16.length);for(let i=0;i<i16.length;i++)rec[i]=i16[i]/32768;
const peaks=M.findPeaks(rec,SR);
let ok=0,silentWrong=0;const gt=process.argv[4]?fs.readFileSync(process.argv[4]):null;
let gtBlocks=null;if(gt){const data=new Uint8Array(gt.buffer,gt.byteOffset,gt[gt.length-1]===10?gt.length-1:gt.length);gtBlocks=M.makeBlocks(data).blocks;}
for(const pk of peaks){const d=M.decodeChirp(rec,SR,pk.p);if(d&&d.ok){ok++;M.learnFrom(d);
  // silent-wrong check: чи декодований блок реально дорівнює якомусь істинному?
  if(gtBlocks){const match=gtBlocks.some(b=>b.length===d.full.length&&b.every((x,i)=>x===d.full[i]));if(!match)silentWrong++;}
}}
const bad=M.dropBadCarriers();
const name=process.argv[2].replace(/.*\//,'');
console.log(`${name.padEnd(48)} | NCAR=${meta.FREQS.length} chirps=${peaks.length} декод=${ok}/${peaks.length} | навч.викинув=${bad?bad.length:0} ${bad&&bad.length?'('+bad.join(',')+')':''} | SILENT-WRONG=${silentWrong}`);
