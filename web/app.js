'use strict';

const $ = id => document.getElementById(id);
const form = $('parameters');
const portable = $('mcoc-pack') ? JSON.parse($('mcoc-pack').textContent) : null;
let worker, jobId=0;
const jobs=new Map();
let defaults, meta, data, frame = 0, timer = null, busy = false, lookup, lastHeatmap;
const num = (v, n = 1) => Number(v).toLocaleString('es-CL', { maximumFractionDigits:n, minimumFractionDigits:n });
const palette = [[40,16,78],[101,53,117],[178,73,115],[240,145,73],[246,232,121]];
const colors = { center_c:'#2563eb', max_c:'#f08a38', mean_c:'#8c67c3' };

function temperatureColor(t,low=data.colorLow,high=data.colorHigh) {
  const x = Math.max(0, Math.min(0.999999, (t-low)/(high-low)))*4;
  const a = Math.floor(x), f = x-a;
  return palette[a].map((v,j) => Math.round(v*(1-f)+palette[a+1][j]*f));
}
function sizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio||1, 2);
  const width = Math.max(1,Math.round(rect.width*dpr)), height = Math.max(1,Math.round(rect.height*dpr));
  if(canvas.width!==width || canvas.height!==height){canvas.width=width;canvas.height=height;}
  return {w:rect.width,h:rect.height,dpr};
}
function context2d(id) {
  const canvas = $(id), box = sizeCanvas(canvas), ctx = canvas.getContext('2d');
  ctx.setTransform(box.dpr,0,0,box.dpr,0,0);ctx.clearRect(0,0,box.w,box.h);
  return {ctx,...box};
}
function timeText(seconds) {return data&&data.time_s.at(-1)>=172800?`${num(seconds/86400,2)} días`:`${num(seconds/3600,2)} h`;}
function showError(message) {$('error').textContent=message;$('error').classList.remove('hidden');}
function state(message,kind='') {$('state').textContent=message;$('state-dot').className='state-dot '+kind;}
function stop() {if(timer)clearInterval(timer);timer=null;$('play').textContent='▶';$('play').setAttribute('aria-label','Reproducir evolución');}

function updateFields() {
  const main = $('boundary_type').value, base = $('bottom_type').value, mode = $('mode').value;
  $('main-temperature').classList.toggle('hidden',main==='neumann');
  $('main-h').classList.toggle('hidden',main!=='robin');
  $('main-flux').classList.toggle('hidden',main!=='neumann');
  $('resistance-field').classList.toggle('hidden',main!=='robin');
  $('boundary-c-label').textContent=main==='dirichlet'?'Cara impuesta':'Aire';
  $('bottom-temperature').classList.toggle('hidden',base==='neumann');
  $('bottom-h').classList.toggle('hidden',base!=='robin');
  $('bottom-flux').classList.toggle('hidden',base!=='neumann');
  $('amplitude-field').classList.toggle('hidden',$('profile').value!=='seno');
  const pulse=$('source_type').value==='cosine';
  $('pulse-source-fields').classList.toggle('hidden',!pulse);
  $('constant-source-field').classList.toggle('hidden',pulse);
  $('resolution-field').classList.toggle('hidden',mode!=='fundacion');
  $('nodes-field').classList.toggle('hidden',mode==='fundacion');
  $('foundation-geometry').classList.toggle('hidden',mode!=='fundacion');
  const original=$('foundation_geometry').value==='ifc';
  ['foundation_x_m','foundation_y_m','foundation_height_m'].forEach((name,i)=>{
    $(name).readOnly=original;
    if(original&&meta)$(name).value=Number(meta.ifc.lengths_m[i].toFixed(4));
  });
  const cube=mode==='3d'&&$('box-shape').value==='cube';
  $('box-geometry').classList.toggle('hidden',mode!=='2d'&&mode!=='3d');
  $('box-shape-field').classList.toggle('hidden',mode!=='3d');
  $('lx-label').textContent=cube?'Lado del cubo':'Lx';
  $('ly-field').classList.toggle('hidden',cube);
  $('lz-field').classList.toggle('hidden',mode!=='3d'||cube);
  if(cube){$('length_y_m').value=$('length_x_m').value;$('length_z_m').value=$('length_x_m').value;}
  $('nodes-label').textContent=mode==='1d'?'Nodos del perfil':'Celdas por eje';
  $('nodes').max=mode==='1d'?401:48;
  $('case-note').textContent=mode==='fundacion'?(original?'IFC de referencia. Vertidas como capas geométricas, sin cronograma.':'Ensayo con IFC escalado: las nuevas dimensiones sí intervienen en el cálculo térmico.'):mode==='1d'?'Altura del IFC. Borde principal: superior; base: inferior.':'Caja sintética. Base: y− en 2D, z− en 3D.';
}
function casePreset(mode,defaults) {
  const values={...defaults,mode};
  if(mode!=='fundacion')Object.assign(values,{initial_c:20,profile:'seno',amplitude_c:20,duration_days:mode==='1d'?14:0.25,boundary_type:'dirichlet',boundary_c:20,bottom_type:'dirichlet',bottom_c:20,nodes:mode==='1d'?67:32});
  if(mode==='3d')Object.assign(values,{source_type:'cosine',duration_days:4,source_duration_days:2,profile:'uniforme',amplitude_c:0,bottom_type:'neumann'});
  return values;
}
function preset(mode) {
  $('box-shape').value='cube';
  const values=casePreset(mode,defaults);
  for(const [name,value] of Object.entries(values)) {const el=form.elements.namedItem(name);if(el)el.value=value===null?'':value;}
  updateFields();
}
function options() {
  const result={};
  for(const name of Object.keys(defaults)) {
    const value=form.elements.namedItem(name).value;
    result[name]=typeof defaults[name]==='number'?Number(value):name==='dt_s'?(value===''?null:Number(value)):value;
  }
  return result;
}
async function request(url,body) {
  if(portable) {
    if(url==='/api/meta')return portable.meta;
    if(url!=='/api/run')throw Error('Operación no incluida en el visor portátil');
    if(!worker){
      const uri=URL.createObjectURL(new Blob([$('mcoc-worker').textContent],{type:'text/javascript'}));
      worker=new Worker(uri);URL.revokeObjectURL(uri);
      worker.onmessage=e=>{const job=jobs.get(e.data.id);if(!job)return;jobs.delete(e.data.id);e.data.error?job.reject(Error(e.data.error)):job.resolve(e.data.result);};
      worker.onerror=e=>{for(const job of jobs.values())job.reject(Error(e.message||'No se pudo iniciar el cálculo local'));jobs.clear();worker.terminate();worker=null;};
    }
    return new Promise((resolve,reject)=>{const id=++jobId;jobs.set(id,{resolve,reject});worker.postMessage({id,options:body,pack:portable});});
  }
  const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
  const result=await response.json();if(!response.ok)throw Error(result.error||'No se pudo completar la operación');return result;
}
async function calculate(event) {
  event?.preventDefault();if(busy||!form.reportValidity())return;
  busy=true;stop();$('error').classList.add('hidden');$('controls').disabled=true;$('download').disabled=true;
  $('calculate').classList.add('busy');$('calculate-label').textContent='Calculando…';
  $('stage-placeholder').classList.remove('hidden');state(portable?'Calculando temperaturas en este navegador…':'Resolviendo temperaturas con el solver del proyecto…');
  const start=performance.now();
  try {
    const payload=options();data=await request('/api/run',payload);
    data.colorLow=Math.min(...data.history.min_c);data.colorHigh=Math.max(...data.history.max_c);
    if(data.colorHigh-data.colorLow<0.01){data.colorLow-=0.5;data.colorHigh+=0.5;}
    lookup=new Int32Array(data.shape.reduce((a,b)=>a*b,1)).fill(-1);
    data.active_indices.forEach((id,index)=>{lookup[id]=index;});
    frame=data.time_s.length-1;$('time-slider').max=frame;$('time-slider').value=frame;$('time-slider').disabled=false;$('play').disabled=false;
    $('download').disabled=false;$('duration-label').textContent=timeText(data.time_s.at(-1));
    const names={fundacion:'Fundación G8 · campo térmico 3D','1d':'Perfil nodal · solución 1D','2d':'Caja de ensayo · solución 2D','3d':'Caja de ensayo · solución 3D'};
    $('model-title').textContent=names[data.mode];
    $('model-subtitle').textContent=data.mode==='fundacion'?`${data.ifc.file} · ${data.lengths_m.map(v=>num(v,2)).join(' × ')} m`:`Datos sintéticos · ${data.lengths_m.slice(0,data.dimension).map(v=>num(v,2)).join(' × ')} m`;
    $('source-label').textContent=data.ifc?`IFC${data.parameters.foundation_geometry==='scaled'&&data.mode==='fundacion'?' escalado':''} · ${data.ifc.sha256.slice(0,8)}`:'Caja sintética';
    $('geometry-chip').textContent=data.mode==='fundacion'?`${data.pour_plan.layers.length} vertidas · ${num(data.stats.cells,0)} celdas activas`:`${data.shape.join(' × ')} ${data.dimension===1?'nodos':'celdas'}`;
    $('model-color').disabled=!data.pour_plan;
    if(!data.pour_plan)$('model-color').value='temperature';
    showPourPlan();
    $('probe-caption').textContent='Posición: '+data.probe_position_m.slice(0,data.dimension).map(v=>num(v,3)).join(', ')+' m';
    $('model-canvas').classList.toggle('hidden',data.dimension!==3);$('flat-canvas').classList.toggle('hidden',data.dimension===3);
    $('view-mode').disabled=data.dimension!==3;$('camera-reset').disabled=data.dimension!==3;
    $('model-hint').textContent=data.dimension===3?'Arrastra para girar · rueda para acercar':'Valores calculados · escala de color fija durante el tiempo';
    $('boundary-used').textContent='Principal: '+data.boundary_used.laterales_y_expuestas;
    $('bottom-used').textContent='Base: '+data.boundary_used.base;
    $('calculation-used').textContent=`${num(data.stats.steps,0)} pasos · Δt ${num(data.stats.dt_s,3)} s · límite ${num(data.stats.limit_dt_s,3)} s`;
    $('balance-used').textContent=data.stats.balance_relative_error===null?'Energía del perfil por unidad de área.':`Residuo relativo de energía: ${data.stats.balance_relative_error.toExponential(2)}`;
    $('legend-low').textContent=num(data.colorLow,1);$('legend-high').textContent=num(data.colorHigh,1);
    if(data.dimension===3)renderer.setData(data);
    $('view-mode').value='full';$('clip-slider').value=50;updateClip();
    $('slice-plane').value=data.dimension===2?'xy':'xz';setupSlice();
    $('stage-placeholder').classList.add('hidden');draw();
    state(`Cálculo completado · ${num((performance.now()-start)/1000,1)} s · ${data.time_s.length} estados guardados`,'ready');
  } catch(error) {showError(error.message);state('Revisa los parámetros y vuelve a calcular.');$('stage-placeholder').classList.add('hidden');}
  finally {busy=false;$('controls').disabled=false;$('calculate').classList.remove('busy');$('calculate-label').textContent='Calcular temperaturas';}
}

function at(i,j=0,k=0) {
  const [,ny=1,nz=1]=data.shape;
  const index=lookup[(i*ny+j)*nz+k];return index>=0?data.frames_c[frame][index]:NaN;
}
function sliceInfo() {
  const plane=$('slice-plane').value;
  const axes=plane==='xy'?[0,1,2]:plane==='yz'?[1,2,0]:[0,2,1];
  return {axes,nu:data.shape[axes[0]],nv:data.shape[axes[1]],fixed:Number($('slice-slider').value)};
}
function setupSlice() {
  const is3d=data.dimension===3;
  $('slice-plane').disabled=!is3d;$('slice-slider').disabled=!is3d;
  $('slice-title').textContent=is3d?'Corte de temperatura':'Perfil central';
  const axis=sliceInfo().axes[2], count=is3d?data.shape[axis]:1;
  $('slice-slider').max=count-1;$('slice-slider').value=Math.floor(count/2);
}
function heatmap(id,primary=false) {
  const {ctx,w,h}=context2d(id), margin={l:48,r:16,t:14,b:34};
  const box={x:margin.l,y:margin.t,w:w-margin.l-margin.r,h:h-margin.t-margin.b};
  const info=primary?{axes:[0,1,2],nu:data.shape[0],nv:data.shape[1],fixed:0}:sliceInfo();
  const {axes,nu,nv,fixed}=info;
  if(!nu||!nv)return;
  const pixels=document.createElement('canvas');pixels.width=nu;pixels.height=nv;
  const pctx=pixels.getContext('2d'), im=pctx.createImageData(nu,nv);
  for(let u=0;u<nu;u++)for(let v=0;v<nv;v++) {
    const indices=[0,0,0];indices[axes[0]]=u;indices[axes[1]]=v;indices[axes[2]]=fixed;
    const t=at(...indices), offset=((nv-1-v)*nu+u)*4;
    const rgb=Number.isFinite(t)?temperatureColor(t):(primary?[18,36,55]:[241,244,248]);
    im.data.set([...rgb,255],offset);
  }
  pctx.putImageData(im,0,0);ctx.imageSmoothingEnabled=false;ctx.drawImage(pixels,box.x,box.y,box.w,box.h);
  const ink=primary?'#a4b4c7':'#62738b';ctx.font='10px Inter, system-ui, sans-serif';ctx.fillStyle=ink;
  ctx.strokeStyle=primary?'#496079':'#d8e0ea';ctx.strokeRect(box.x,box.y,box.w,box.h);
  for(let n=0;n<=4;n++) {
    const f=n/4;
    ctx.textAlign='center';ctx.fillText(num(data.origin_m[axes[0]]+f*data.lengths_m[axes[0]],2),box.x+f*box.w,box.y+box.h+16);
    ctx.textAlign='right';ctx.fillText(num(data.origin_m[axes[1]]+f*data.lengths_m[axes[1]],2),box.x-7,box.y+(1-f)*box.h+3);
  }
  ctx.textAlign='center';ctx.fillText('xyz'[axes[0]]+' [m]',box.x+box.w/2,h-3);
  ctx.save();ctx.translate(11,box.y+box.h/2);ctx.rotate(-Math.PI/2);ctx.fillText('xyz'[axes[1]]+' [m]',0,0);ctx.restore();
  if(!primary){lastHeatmap={...info,box};const coord=data.origin_m[axes[2]]+(fixed+0.5)*data.spacing_m[axes[2]];
    $('slice-position').textContent=`${'xyz'[axes[2]]} = ${num(coord,3)} m`;$('slice-caption').textContent='Color de cada celda activa · mueve el cursor para consultar';}
}

function lineChart(id,series,xs,options={}) {
  const {ctx,w,h}=context2d(id), dark=!!options.dark, ink=dark?'#a4b4c7':'#62738b';
  const box={x:48,y:20,w:w-67,h:h-57};
  const values=series.flatMap(s=>s.values);let lo=Math.min(...values),hi=Math.max(...values);
  const pad=Math.max(0.5,(hi-lo)*0.12);lo-=pad;hi+=pad;
  if(options.minY!==undefined)lo=options.minY;
  const end=Math.max(xs.at(-1),1e-9), tx=x=>box.x+x/end*box.w, ty=t=>box.y+(hi-t)/(hi-lo)*box.h;
  ctx.font='10px Inter, system-ui, sans-serif';
  for(let i=0;i<=4;i++) {const f=i/4,y=box.y+f*box.h;ctx.strokeStyle=dark?'#30465d':'#edf0f5';ctx.beginPath();ctx.moveTo(box.x,y);ctx.lineTo(w-18,y);ctx.stroke();ctx.fillStyle=ink;ctx.textAlign='right';ctx.fillText(num(hi-f*(hi-lo),1),box.x-7,y+3);ctx.textAlign='center';ctx.fillText(num(f*end,options.xDecimals??1),tx(f*end),box.y+box.h+17);}
  for(const s of series) {ctx.strokeStyle=s.color;ctx.lineWidth=s.width||2;ctx.setLineDash(s.dashed?[6,4]:[]);ctx.beginPath();s.values.forEach((v,i)=>i?ctx.lineTo(tx(xs[i]),ty(v)):ctx.moveTo(tx(xs[i]),ty(v)));ctx.stroke();ctx.setLineDash([]);
    if(options.frame!==undefined){ctx.fillStyle=s.color;ctx.beginPath();ctx.arc(tx(xs[options.frame]),ty(s.values[options.frame]),4,0,2*Math.PI);ctx.fill();}}
  if(options.cursor!==undefined){ctx.setLineDash([3,3]);ctx.strokeStyle=dark?'#c2d1e4':'#98aac1';ctx.beginPath();ctx.moveTo(tx(options.cursor),box.y);ctx.lineTo(tx(options.cursor),box.y+box.h);ctx.stroke();ctx.setLineDash([]);}
  ctx.fillStyle=ink;ctx.textAlign='center';ctx.fillText(options.xLabel||'Tiempo [días]',box.x+box.w/2,h-3);
  ctx.save();ctx.translate(12,box.y+box.h/2);ctx.rotate(-Math.PI/2);ctx.fillText(options.yLabel||'Temperatura [°C]',0,0);ctx.restore();
}
function profile(id,dark=false) {
  const nx=data.shape[0], y=data.dimension===2?Math.floor(data.shape[1]/2):0;
  const values=Array.from({length:nx},(_,i)=>at(i,y));
  const xs=Array.from({length:nx},(_,i)=>data.origin_m[0]+(data.dimension===1?i:i+0.5)*data.spacing_m[0]);
  lineChart(id,[{values,color:dark?'#f3b05b':'#2563eb'}],xs,{dark,xLabel:data.dimension===1?'Altura z [m]':'x [m]',xDecimals:2});
  if(!dark){$('slice-position').textContent=data.dimension===1?'Perfil nodal':`y = ${num((y+0.5)*data.spacing_m[1],3)} m`;$('slice-caption').textContent='Temperatura calculada en los nodos / centros del perfil';}
}
function historySeries(result) {
  const series=Object.entries(colors).map(([key,color])=>({name:{center_c:'Central',max_c:'Máxima',mean_c:'Media'}[key],values:result.history[key],color}));
  const o=result.parameters;
  if(o.boundary_type==='dirichlet')series.push({name:`Dirichlet principal: ${o.boundary_c} °C`,values:result.time_s.map(()=>o.boundary_c),color:'#0891b2',dashed:true});
  if(o.bottom_type==='dirichlet')series.push({name:`Dirichlet base: ${o.bottom_c} °C`,values:result.time_s.map(()=>o.bottom_c),color:'#dc2626',dashed:true});
  return series;
}
function historyFrameAt(times,fraction) {
  const target=Math.max(0,Math.min(1,fraction))*times.at(-1);
  return times.reduce((best,t,i)=>Math.abs(t-target)<Math.abs(times[best]-target)?i:best,0);
}
function showPourPlan() {
  $('pour-plan').classList.toggle('hidden',!data.pour_plan);
  $('pour-rows').replaceChildren();
  if(!data.pour_plan)return;
  const rows=data.pour_plan.layers;
  $('pour-summary').textContent=`${rows.length} capas de igual altura · volumen voxelizado total ${num(rows.reduce((s,r)=>s+r.voxel_volume_m3,0),2)} m³ · todas presentes desde t = 0`;
  for(const row of rows){
    const tr=document.createElement('tr');
    for(const value of [`Vertida ${row.id}`,num(row.z_min_m,3),num(row.z_max_m,3),num(row.cells,0),num(row.voxel_volume_m3,2)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    tr.firstChild.style.borderLeft=`5px solid rgb(${temperatureColor((row.id-.5)/rows.length,0,1).join(',')})`;
    $('pour-rows').append(tr);
  }
}
function pourColorsActive(){return !!data?.pour_plan&&$('model-color').value==='pours';}
function modelValues(){return pourColorsActive()?data.pour_plan.cell_pour_id.map(id=>(id-.5)/data.pour_plan.layers.length):data.frames_c[frame];}
function heightProfiles(result,current) {
  const dim=result.dimension, axis=dim-1, n=result.shape[axis], nodal=dim===1;
  const mid=result.shape.map(v=>Math.floor(v/2));
  const index=new Map(result.active_indices.map((id,i)=>[id,i]));
  const cells=[];
  for(let j=0;j<n;j++){const at=mid.slice();at[axis]=j;const id=at.reduce((flat,v,a)=>flat*result.shape[a]+v,0);if(index.has(id))cells.push(index.get(id));}
  const heights=cells.map(i=>result.positions_m[i][axis]);
  const lower=!nodal&&result.parameters.bottom_type==='dirichlet';
  const upper=!nodal&&result.parameters.boundary_type==='dirichlet';
  if(lower)heights.unshift(result.origin_m[axis]);
  if(upper)heights.push(result.origin_m[axis]+result.lengths_m[axis]);
  const frames=[...new Set([0,.25,.5,.75,1].map(f=>historyFrameAt(result.time_s,f)).concat(current))].sort((a,b)=>a-b);
  const shades=['#2563eb','#0891b2','#8b5cf6','#ea580c','#dc2626','#16a34a'];
  return {heights,series:frames.map((f,i)=>{const values=cells.map(j=>result.frames_c[f][j]);if(lower)values.unshift(result.parameters.bottom_c);if(upper)values.push(result.parameters.boundary_c);return {values,color:shades[i],width:f===current?3.5:1.7,dashed:f!==current,frame:f};})};
}
function draw() {
  if(!data)return;
  const layers=pourColorsActive();
  $('model-legend-title').textContent=layers?'VERTIDAS · CAPAS':'TEMPERATURA °C';
  $('legend-low').textContent=layers?'Vertida 1':num(data.colorLow,1);
  $('legend-high').textContent=layers?`Vertida ${data.pour_plan.layers.length}`:num(data.colorHigh,1);
  for(const [id,key] of [['max-value','max_c'],['center-value','center_c'],['mean-value','mean_c']])$(id).innerHTML=`${num(data.history[key][frame],1)}<small> °C</small>`;
  const days=data.time_s.at(-1)>=172800, value=data.time_s[frame]/(days?86400:3600);
  $('time-value').innerHTML=`${num(value,2)}<small> ${days?'días':'h'}</small>`;
  $('frame-caption').textContent=`Estado ${frame+1} de ${data.time_s.length}`;$('timeline-time').textContent=timeText(data.time_s[frame]);
  if(data.dimension===3)renderer.draw();else if(data.dimension===2)heatmap('flat-canvas',true);else profile('flat-canvas',true);
  if(data.dimension===3)heatmap('slice-canvas');else profile('slice-canvas');
  const unit=days?86400:3600;
  const series=historySeries(data);
  lineChart('history-canvas',series,data.time_s.map(t=>t/unit),{cursor:data.time_s[frame]/unit,frame,xLabel:days?'Tiempo [días]':'Tiempo [h]'});
  $('history-caption').textContent=`${timeText(data.time_s[frame])} · interior central ${num(data.history.center_c[frame],2)} °C · pulsa el gráfico para recorrer el tiempo`;
  $('history-legend').replaceChildren(...series.map(s=>{const item=document.createElement('span'),mark=document.createElement('i');mark.style.background=s.color;item.append(mark,document.createTextNode(s.name));return item;}));
  const profiles=heightProfiles(data,frame);
  lineChart('height-canvas',profiles.series,profiles.heights,{xLabel:'Altura [m]',xDecimals:2});
  $('height-caption').textContent=`Columna central · línea gruesa: ${timeText(data.time_s[frame])} · extremos Dirichlet incluidos cuando están prescritos`;
  $('height-legend').replaceChildren(...profiles.series.map(s=>{const item=document.createElement('span'),mark=document.createElement('i');mark.style.background=s.color;item.append(mark,document.createTextNode(timeText(data.time_s[s.frame])+(s.frame===frame?' · seleccionado':'')));return item;}));
  const source=data.source_curve;
  lineChart('source-canvas',[{values:source.rate_w_m3,color:'#ea580c'}],source.time_s.map(t=>t/unit),{cursor:data.time_s[frame]/unit,minY:Math.min(...source.rate_w_m3)>=0?0:undefined,xLabel:days?'Tiempo [días]':'Tiempo [h]',yLabel:'Q(t) [W/m³]'});
  const peak=Math.max(...data.history.center_c);
  const zeroSource=source.rate_w_m3.every(q=>q===0);
  $('source-caption').textContent=(zeroSource?'Sin generación de calor: Q(t) = 0. Selecciona el pulso en Tipo de fuente y pulsa Calcular temperaturas. ':data.parameters.source_type==='cosine'?`Qmax ${num(data.parameters.qmax_w_m3,1)} W/m³ · τ ${num(data.parameters.source_duration_days,2)} días · `:`Fuente constante ${num(data.parameters.source_w_m3,1)} W/m³ · `)+`máximo central guardado: ${num(peak,2)} °C.`;
}

// Matrices columna mayor; cámara orbital con z vertical, como en el IFC.
function multiply(a,b) {const out=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)out[c*4+r]+=a[k*4+r]*b[c*4+k];return out;}
function mvp(yaw,elevation,distance,aspect) {
  const eye=[Math.cos(yaw)*Math.cos(elevation)*distance,Math.sin(yaw)*Math.cos(elevation)*distance,Math.sin(elevation)*distance];
  const norm=v=>{const n=Math.hypot(...v);return v.map(x=>x/n);};
  const z=norm(eye),x=norm([-z[1],z[0],0]),y=[z[1]*x[2]-z[2]*x[1],z[2]*x[0]-z[0]*x[2],z[0]*x[1]-z[1]*x[0]];
  const dot=(a,b)=>a.reduce((v,t,i)=>v+t*b[i],0);
  const view=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);
  const f=1/Math.tan(Math.PI/8),near=0.1,far=30;
  const projection=new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0]);
  return multiply(projection,view);
}
class ThermalRenderer {
  constructor(canvas) {
    this.canvas=canvas;this.yaw=-0.9;this.elevation=0.68;this.distance=3.5;
    this.gl=canvas.getContext('webgl2',{antialias:true,preserveDrawingBuffer:true});
    if(this.gl){try{this.initGL();}catch(error){const replacement=canvas.cloneNode();canvas.replaceWith(replacement);canvas=replacement;this.canvas=canvas;this.gl=null;}}
    if(!this.gl)this.ctx=canvas.getContext('2d');
    let drag=null;
    canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!drag)return;this.yaw-=(e.clientX-drag[0])*0.008;this.elevation=Math.max(0.08,Math.min(1.48,this.elevation+(e.clientY-drag[1])*0.008));drag=[e.clientX,e.clientY];this.draw();});
    canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('pointercancel',()=>drag=null);
    canvas.addEventListener('wheel',e=>{e.preventDefault();this.distance=Math.max(2.5,Math.min(8,this.distance+e.deltaY*0.003));this.draw();},{passive:false});
  }
  initGL() {
    const gl=this.gl;
    const vertex=`#version 300 es
    precision highp float;layout(location=0)in vec3 vertex;layout(location=1)in vec3 normal;
    layout(location=2)in vec3 position;layout(location=3)in float temperature;
    uniform mat4 matrix;uniform vec3 center;uniform vec3 delta;uniform float scale;uniform int cutMode;uniform float cut;
    out float temp;out vec3 faceNormal;flat out int visible;
    void main(){visible=((cutMode==1&&position.x>cut)||(cutMode==2&&position.z>cut))?0:1;
    gl_Position=matrix*vec4((position-center+vertex*delta*0.97)*scale,1.0);temp=temperature;faceNormal=normal;}`;
    const fragment=`#version 300 es
    precision highp float;in float temp;in vec3 faceNormal;flat in int visible;uniform float low;uniform float high;out vec4 color;
    void main(){if(visible==0)discard;float x=clamp((temp-low)/(high-low),0.0,0.99999)*4.0;
    vec3 a[5]=vec3[5](vec3(40,16,78),vec3(101,53,117),vec3(178,73,115),vec3(240,145,73),vec3(246,232,121));
    int i=int(floor(x));vec3 c=mix(a[i],a[i+1],fract(x))/255.0;
    float light=0.78+0.22*max(dot(normalize(faceNormal),normalize(vec3(-0.5,-0.4,1))),0.0);color=vec4(c*light,1);}`;
    const compile=(kind,source)=>{const s=gl.createShader(kind);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
    this.program=gl.createProgram();gl.attachShader(this.program,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(this.program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(this.program);
    if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error('No se pudo crear la vista 3D');
    this.locations=Object.fromEntries(['matrix','center','delta','scale','low','high','cutMode','cut'].map(n=>[n,gl.getUniformLocation(this.program,n)]));
    this.vao=gl.createVertexArray();gl.bindVertexArray(this.vao);
    const vertices=[], faces=[[[1,0,0],[[1,-1,-1],[1,1,-1],[1,1,1],[1,-1,1]]],[[-1,0,0],[[-1,1,-1],[-1,-1,-1],[-1,-1,1],[-1,1,1]]],[[0,1,0],[[1,1,-1],[-1,1,-1],[-1,1,1],[1,1,1]]],[[0,-1,0],[[-1,-1,-1],[1,-1,-1],[1,-1,1],[-1,-1,1]]],[[0,0,1],[[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]]],[[0,0,-1],[[-1,1,-1],[1,1,-1],[1,-1,-1],[-1,-1,-1]]]];
    for(const [normal,corners] of faces)for(const index of [0,1,2,0,2,3])vertices.push(...corners[index].map(v=>v/2),...normal);
    const mesh=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,mesh);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,24,0);gl.enableVertexAttribArray(1);gl.vertexAttribPointer(1,3,gl.FLOAT,false,24,12);
    this.positionBuffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.positionBuffer);gl.enableVertexAttribArray(2);gl.vertexAttribPointer(2,3,gl.FLOAT,false,0,0);gl.vertexAttribDivisor(2,1);
    this.temperatureBuffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.temperatureBuffer);gl.enableVertexAttribArray(3);gl.vertexAttribPointer(3,1,gl.FLOAT,false,0,0);gl.vertexAttribDivisor(3,1);
    gl.enable(gl.DEPTH_TEST);
  }
  setData(value) {
    this.value=value;this.lastFrame=-1;this.maxLength=Math.max(...value.lengths_m);this.center=value.origin_m.map((x,i)=>x+value.lengths_m[i]/2);
    if(this.gl){const gl=this.gl;gl.bindBuffer(gl.ARRAY_BUFFER,this.positionBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(value.positions_m.flat()),gl.STATIC_DRAW);}
  }
  reset() {this.yaw=-0.9;this.elevation=0.68;this.distance=3.5;this.draw();}
  draw() {
    if(!this.value||data?.dimension!==3)return;
    const box=sizeCanvas(this.canvas), matrix=mvp(this.yaw,this.elevation,this.distance,box.w/box.h);
    const mode=$('view-mode').value, axis=mode==='x'?0:2;
    const cut=data.origin_m[axis]+data.lengths_m[axis]*Number($('clip-slider').value)/100;
    if(!this.gl){this.software(matrix,box,mode,cut);return;}
    const gl=this.gl,L=this.locations;gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.program);gl.bindVertexArray(this.vao);gl.uniformMatrix4fv(L.matrix,false,matrix);gl.uniform3fv(L.center,this.center);gl.uniform3fv(L.delta,data.spacing_m);gl.uniform1f(L.scale,2/this.maxLength);
    gl.uniform1f(L.low,pourColorsActive()?0:data.colorLow);gl.uniform1f(L.high,pourColorsActive()?1:data.colorHigh);gl.uniform1i(L.cutMode,mode==='x'?1:mode==='z'?2:0);gl.uniform1f(L.cut,cut);
    const frameKey=`${frame}:${$('model-color').value}`;
    if(this.lastFrame!==frameKey){gl.bindBuffer(gl.ARRAY_BUFFER,this.temperatureBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(modelValues()),gl.DYNAMIC_DRAW);this.lastFrame=frameKey;}
    gl.drawArraysInstanced(gl.TRIANGLES,0,36,data.positions_m.length);
  }
  software(matrix,box,mode,cut) {
    // Respaldo sin GPU: proyecta centros superficiales del mismo campo calculado.
    const ctx=this.ctx;ctx.setTransform(box.dpr,0,0,box.dpr,0,0);ctx.clearRect(0,0,box.w,box.h);
    const visible=p=>mode==='full'||p[mode==='x'?0:2]<=cut;
    const [nx,ny,nz]=data.shape, entries=[];
    const keep=(i,j,k)=>{if(i<0||j<0||k<0||i>=nx||j>=ny||k>=nz)return false;const q=lookup[(i*ny+j)*nz+k];return q>=0&&visible(data.positions_m[q]);};
    for(let q=0;q<data.positions_m.length;q++) {
      const p=data.positions_m[q];if(!visible(p))continue;
      const flat=data.active_indices[q],i=Math.floor(flat/(ny*nz)),j=Math.floor(flat/nz)%ny,k=flat%nz;
      if(keep(i-1,j,k)&&keep(i+1,j,k)&&keep(i,j-1,k)&&keep(i,j+1,k)&&keep(i,j,k-1)&&keep(i,j,k+1))continue;
      const v=p.map((x,a)=>(x-this.center[a])*2/this.maxLength), out=[0,0,0,0];
      for(let r=0;r<4;r++)out[r]=matrix[r]*v[0]+matrix[4+r]*v[1]+matrix[8+r]*v[2]+matrix[12+r];
      if(out[3]<=0)continue;
      entries.push({x:(out[0]/out[3]+1)*box.w/2,y:(1-out[1]/out[3])*box.h/2,z:out[2]/out[3],q,size:Math.max(2,box.h*data.spacing_m[0]/this.maxLength/out[3]*2.5)});
    }
    entries.sort((a,b)=>b.z-a.z);
    const values=modelValues(),layers=pourColorsActive();
    for(const p of entries){ctx.fillStyle=`rgb(${temperatureColor(values[p.q],layers?0:data.colorLow,layers?1:data.colorHigh).join(',')})`;ctx.fillRect(p.x-p.size/2,p.y-p.size/2,p.size,p.size);}
  }
}
let renderer;
function updateClip(){const open=$('view-mode').value!=='full'&&data?.dimension===3;$('clip-control').classList.toggle('hidden',!open);$('clip-caption').textContent=$('clip-slider').value+' %';if(renderer&&data?.dimension===3)renderer.draw();}

form.addEventListener('submit',calculate);
$('model-color').addEventListener('change',draw);
function selectTab(section) {
  for(const name of ['laboratory','project']){
    const active=name===section;
    $('tab-'+name).setAttribute('aria-selected',String(active));$('tab-'+name).tabIndex=active?0:-1;
    $('panel-'+name).classList.toggle('hidden',!active);
  }
  if(section==='laboratory')requestAnimationFrame(draw);
}
['laboratory','project'].forEach((name,index)=>{
  $('tab-'+name).addEventListener('click',()=>selectTab(name));
  $('tab-'+name).addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const next=event.key==='Home'?'laboratory':event.key==='End'?'project':['laboratory','project'][1-index];
    selectTab(next);$('tab-'+next).focus();
  });
});
form.addEventListener('input',()=>{updateFields();if(data&&!busy)state('Parámetros modificados · pulsa Calcular para actualizar el resultado.','dirty');});
$('mode').addEventListener('change',()=>{preset($('mode').value);state('Caso modificado · pulsa Calcular para resolverlo.','dirty');});
$('reset').addEventListener('click',()=>{preset($('mode').value);state('Parámetros restablecidos · pulsa Calcular.','dirty');});
$('time-slider').addEventListener('input',()=>{stop();frame=Number($('time-slider').value);draw();});
$('history-canvas').addEventListener('click',event=>{if(!data)return;const rect=event.currentTarget.getBoundingClientRect();stop();frame=historyFrameAt(data.time_s,(event.clientX-rect.left-48)/(rect.width-67));$('time-slider').value=frame;draw();});
$('play').addEventListener('click',()=>{if(timer){stop();return;}if(!data)return;if(frame===data.time_s.length-1)frame=0;$('time-slider').value=frame;$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','Pausar evolución');draw();timer=setInterval(()=>{frame++;if(frame>=data.time_s.length){stop();frame=data.time_s.length-1;} $('time-slider').value=frame;draw();},220);});
$('slice-plane').addEventListener('change',()=>{if(data){setupSlice();draw();}});$('slice-slider').addEventListener('input',draw);
$('view-mode').addEventListener('change',updateClip);$('clip-slider').addEventListener('input',updateClip);$('camera-reset').addEventListener('click',()=>renderer.reset());
$('slice-canvas').addEventListener('mousemove',event=>{
  if(!data||data.dimension!==3||!lastHeatmap)return;
  const rect=event.currentTarget.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,{box,axes,nu,nv,fixed}=lastHeatmap;
  const u=Math.floor((x-box.x)/box.w*nu),v=nv-1-Math.floor((y-box.y)/box.h*nv),tooltip=$('slice-tooltip');
  if(u<0||u>=nu||v<0||v>=nv){tooltip.classList.add('hidden');return;}
  const index=[0,0,0];index[axes[0]]=u;index[axes[1]]=v;index[axes[2]]=fixed;
  const t=at(...index);tooltip.textContent=Number.isFinite(t)?`${num(t,2)} °C · ${index.map((n,a)=>`${'xyz'[a]} ${num(data.origin_m[a]+(n+0.5)*data.spacing_m[a],3)}`).join(' · ')}`:'Fuera del sólido';
  tooltip.style.left=Math.min(x+8,rect.width-260)+'px';tooltip.style.top=Math.max(0,y-32)+'px';tooltip.classList.remove('hidden');
});
$('slice-canvas').addEventListener('mouseleave',()=>$('slice-tooltip').classList.add('hidden'));
$('download').addEventListener('click',()=>{if(!data)return;const file={...data};delete file.colorLow;delete file.colorHigh;const url=URL.createObjectURL(new Blob([JSON.stringify(file)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`mcoc_${data.mode}_resultados.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('portable-download').addEventListener('click',()=>{
  const a=document.createElement('a');a.download='visor_termico.html';
  if(portable){const url=URL.createObjectURL(new Blob(['<!doctype html>\n'+document.documentElement.outerHTML],{type:'text/html;charset=utf-8'}));a.href=url;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  else{a.href='/visor_termico.html';a.click();}
});
let resizeTimer;new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,80);}).observe($('model-stage'));
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(draw,80);});

(async()=>{
  try {
    if(location.protocol==='file:'&&!portable)throw Error('Abre visor_termico.html para el modo portátil, o inicia abrir_visor.cmd para usar Python.');
    renderer=new ThermalRenderer($('model-canvas'));meta=await request('/api/meta');defaults=meta.defaults;
    $('project-ifc').textContent=`IFC de referencia: ${meta.ifc.file} · SHA-256 ${meta.ifc.sha256}. Regenerar el HTML incorpora cambios posteriores guardados en Bonsai.`;
    preset('fundacion');$('connection').textContent=portable?'Portátil · sin conexión':'Solver conectado';
    if(portable){$('case-note').textContent='Geometría IFC incluida en este archivo. Cálculo local sin servidor.';$('portable-download').textContent='↓ Guardar HTML';}
    await calculate();
  } catch(error){showError(error.message);state(portable?'Revisa el mensaje del navegador.':'El servidor local debe estar en ejecución.');$('connection').textContent='Sin conexión';$('stage-placeholder').classList.add('hidden');}
})();
