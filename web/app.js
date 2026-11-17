'use strict';

const $ = id => document.getElementById(id);
const form = $('parameters');
const portable = $('mcoc-pack') ? JSON.parse($('mcoc-pack').textContent) : null;
let worker, jobId=0;
const jobs=new Map();
let defaults, meta, data, frame = 0, timer = null, busy = false, lookup, lastHeatmap, calculatedOptions;
const num = (v, n = 1) => v===null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('es-CL', { maximumFractionDigits:n, minimumFractionDigits:n });
const palette = [[40,16,78],[101,53,117],[178,73,115],[240,145,73],[246,232,121]];
const colors = { center_c:'#2563eb', max_c:'#f08a38', mean_c:'#8c67c3', min_c:'#15805b' };
const hiddenPourIds=new Set();
let pourVisibilityVersion=0;

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
  updateSchedule();
  const main = $('boundary_type').value, base = $('bottom_type').value, mode = $('mode').value;
  const environment = mode==='fundacion'&&$('environment_mode').value==='e10';
  const usesSoil = environment&&$('environment_soil').value==='equivalent';
  $('environment-fields').classList.toggle('hidden',mode!=='fundacion');
  $('environment-options').classList.toggle('hidden',!environment);
  $('manual-exposed-fields').classList.toggle('hidden',environment);
  $('boundary-fields').classList.toggle('hidden',usesSoil);
  for(const id of ['boundary_type','boundary_c','h_w_m2k','flux_in_w_m2','resistance_m2k_w'])$(id).disabled=environment;
  for(const id of ['bottom_type','bottom_c','bottom_h_w_m2k','bottom_flux_in_w_m2'])$(id).disabled=usesSoil;
  const fixedFilm = environment&&$('environment_wind').value==='fixed';
  const scheduled = environment&&$('environment_formwork').value==='scheduled';
  $('environment-h-field').classList.toggle('hidden',!fixedFilm);
  $('environment-strip-field').classList.toggle('hidden',!scheduled);
  $('environment_h').disabled=!fixedFilm;
  $('environment_strip_h').disabled=!scheduled;
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
  if(mode==='fundacion'&&$('construction_mode').value==='staged')$('case-note').textContent='IFC → grilla térmica → activación por cronograma. Solo participa el hormigón colocado.';
}
function updateSchedule() {
  const staged=$('construction_mode').value==='staged';
  $('schedule-editor').classList.toggle('hidden',!staged);
  $('construction-note').textContent=staged?'Por etapas: solo el hormigón colocado participa en el cálculo. Las capas tienen igual altura; el cronograma cambia su evolución térmica.':'División geométrica simultánea: todas las capas están presentes desde t = 0. Cambiar solo su cantidad no cambia las temperaturas.';
  const count=Math.max(1,Math.min(12,Number($('pour_count').value)||1));
  let rows;try{rows=JSON.parse($('pour_schedule').value||'[]');}catch{rows=[];}
  if($('schedule-rows').children.length!==count||!rows.length){
    rows=Array.from({length:count},(_,i)=>rows[i]||{start_days:i,placement_c:Number($('initial_c').value)});
    $('schedule-rows').replaceChildren();
    rows.forEach((row,i)=>{
      const heading=document.createElement('p');heading.textContent=`Vertida ${i+1}`;
      const grid=document.createElement('div');grid.className='form-grid';
      for(const [key,label,min,max] of [['start_days','Inicio [días]',0,30],['placement_c','Colocación [°C]',-50,150]]){
        const wrap=document.createElement('label'),input=document.createElement('input');
        wrap.textContent=label;input.type='number';input.step='any';input.min=min;input.max=max;input.required=true;input.value=row[key];
        input.addEventListener('input',()=>{rows[i][key]=Number(input.value);$('pour_schedule').value=JSON.stringify(rows);});
        wrap.append(input);grid.append(wrap);
      }
      const section=document.createElement('div');section.append(heading,grid);$('schedule-rows').append(section);
    });
    $('pour_schedule').value=JSON.stringify(rows);
  }
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
    const field=form.elements.namedItem(name);
    if(field.disabled){result[name]=defaults[name];continue;}
    const value=field.value;
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
function boundaryFaces(result) {
  // La base es el extremo negativo del último eje del solver, también en 1D.
  const axes=result.dimension===1?['x']:result.dimension===2?['x','y']:['x','y','z'];
  return axes.flatMap((axis,i)=>['−','+'].map(sign=>({
    face:axis+sign,
    condition:result.boundary_used[i===axes.length-1&&sign==='−'?'base':'laterales_y_expuestas']
  })));
}
function simulationSummary(result) {
  const p=result.parameters, dim=result.dimension;
  const source=p.source_type==='cosine'
    ?`Pulso Qmax = ${num(p.qmax_w_m3,0)} W/m³; τ = ${num(p.source_duration_days,3)} días`
    :`Fuente constante = ${num(p.source_w_m3,2)} W/m³`;
  return `Dimensiones: ${result.lengths_m.slice(0,dim).map(v=>num(v,3)).join(' × ')} m${dim===2?' · profundidad 1 m':''}. `+
    `${dim===1?'Separación nodal':'Tamaños de celda'}: ${result.spacing_m.slice(0,dim).map(v=>num(v,5)).join(' × ')} m. `+
    `Malla: ${result.shape.join(' × ')}; ${num(result.stats.cells,0)} ${dim===1?'nodos':'celdas activas'}. `+
    `Duración: ${num(result.time_s.at(-1)/86400,4)} días. ${source}. `+
    `Δt efectivo: ${num(result.stats.dt_s,6)} s (${p.dt_s===null?'automático':'solicitado'}); último paso acortado si corresponde.`;
}
function showSimulationDetails() {
  $('boundary-faces').replaceChildren();
  for(const row of boundaryFaces(data)) {
    const tr=document.createElement('tr');
    for(const value of [row.face,row.condition]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    $('boundary-faces').append(tr);
  }
  $('boundary-face-note').textContent=data.mode==='fundacion'
    ?'Las caras indican orientaciones de la grilla. Las superficies escalonadas expuestas del IFC usan la condición principal; solo el plano inferior usa la base.'
    :data.dimension===1?'x es el eje numérico del perfil vertical: x− = base, x+ = extremo superior.'
    :'La base es '+(data.dimension===2?'y−':'z−')+'. Neumann positivo indica calor entrante; Dirichlet prescribe la temperatura en la cara, no en el centro de celda.';
  if(data.parameters.environment_mode==='e10'){
    const p=data.parameters;
    const wind=p.environment_wind==='synthetic'?'h calculado con viento sintético':`h fijo = ${num(p.environment_h,2)} W/(m²·K)`;
    const solar=p.environment_solar==='synthetic'?'radiación sintética':'sin radiación';
    const mold={none:'sin moldaje',permanent:'moldaje permanente',scheduled:`retiro del moldaje a las ${num(p.environment_strip_h,2)} h`}[p.environment_formwork];
    const insulation=p.environment_insulation==='blanket'?'manta superior':'sin manta superior';
    $('boundary-face-note').textContent=`E10 · aire sintético, ${wind}, ${solar}, ${mold} y ${insulation}.`+
      (p.environment_soil==='equivalent'?' La base usa resistencia térmica equivalente y temperatura profunda fija.':' La base usa el borde manual.');
  }
  $('simulation-summary').textContent=simulationSummary(data);
  if(data.parameters.environment_mode==='e10')$('simulation-summary').textContent+=
    ` E10 limita Δt a ${num(meta.environment.max_step_s,0)} s para resolver el ciclo meteorológico horario.`;
  if(data.construction)$('simulation-summary').textContent+=' Construcción por etapas: fuente por edad local, perfil inicial sustituido por temperaturas de colocación. Δt solicitado actúa como máximo. Las celdas futuras se ocultan.';
}
function refreshPendingChanges() {
  if(!data||busy)return;
  const dirty=JSON.stringify(options())!==calculatedOptions;
  $('pending-changes').classList.toggle('hidden',!dirty);
  state(dirty?'Cambios pendientes de simular · resultados del último cálculo.':'Resultados actualizados con los parámetros del formulario.',dirty?'dirty':'ready');
}
async function calculate(event) {
  event?.preventDefault();if(busy||!form.reportValidity())return;
  busy=true;stop();$('error').classList.add('hidden');$('controls').disabled=true;$('download').disabled=true;
  $('calculate').classList.add('busy');$('calculate-label').textContent='Calculando…';
  $('stage-placeholder').classList.remove('hidden');state(portable?'Calculando temperaturas en este navegador…':'Resolviendo temperaturas con el solver del proyecto…');
  const start=performance.now();
  try {
    const payload=options();const result=await request('/api/run',payload);data=result;
    data.colorLow=Math.min(...data.history.min_c.filter(Number.isFinite));data.colorHigh=Math.max(...data.history.max_c.filter(Number.isFinite));
    if(!Number.isFinite(data.colorLow)){data.colorLow=0;data.colorHigh=1;}
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
    showSimulationDetails();
    $('calculation-used').textContent=`${num(data.stats.steps,0)} pasos · Δt ${num(data.stats.dt_s,3)} s · límite ${num(data.stats.limit_dt_s,3)} s`;
    $('balance-used').textContent=data.stats.balance_relative_error===null?'Energía del perfil por unidad de área.':`Residuo relativo de energía: ${data.stats.balance_relative_error.toExponential(2)}`;
    $('legend-low').textContent=num(data.colorLow,1);$('legend-high').textContent=num(data.colorHigh,1);
    if(data.dimension===3)renderer.setData(data);
    $('view-mode').value='full';$('clip-slider').value=50;updateClip();
    $('slice-plane').value=data.dimension===2?'xy':'xz';setupSlice();
    $('stage-placeholder').classList.add('hidden');draw();
    calculatedOptions=JSON.stringify(payload);$('pending-changes').classList.add('hidden');
    state(`Cálculo completado · ${num((performance.now()-start)/1000,1)} s · ${data.time_s.length} estados guardados`,'ready');
  } catch(error) {showError(error.message);state('Revisa los parámetros y vuelve a calcular.');$('stage-placeholder').classList.add('hidden');}
  finally {busy=false;$('controls').disabled=false;$('download').disabled=!data;$('calculate').classList.remove('busy');$('calculate-label').textContent='Calcular temperaturas';if(data&&JSON.stringify(options())!==calculatedOptions)refreshPendingChanges();}
}

function at(i,j=0,k=0) {
  const [,ny=1,nz=1]=data.shape;
  const index=lookup[(i*ny+j)*nz+k];return index>=0&&data.frames_c[frame][index]!==null?data.frames_c[frame][index]:NaN;
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
  const ink=primary?'#a4b4c7':'#62738b';ctx.font='10px system-ui, sans-serif';ctx.fillStyle=ink;
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
  const values=series.flatMap(s=>s.values).filter(Number.isFinite);let lo=values.length?Math.min(...values):0,hi=values.length?Math.max(...values):1;
  const pad=Math.max(0.5,(hi-lo)*0.12);lo-=pad;hi+=pad;
  if(options.minY!==undefined)lo=options.minY;
  const end=Math.max(xs.at(-1),1e-9), tx=x=>box.x+x/end*box.w, ty=t=>box.y+(hi-t)/(hi-lo)*box.h;
  ctx.font='10px system-ui, sans-serif';
  for(let i=0;i<=4;i++) {const f=i/4,y=box.y+f*box.h;ctx.strokeStyle=dark?'#30465d':'#edf0f5';ctx.beginPath();ctx.moveTo(box.x,y);ctx.lineTo(w-18,y);ctx.stroke();ctx.fillStyle=ink;ctx.textAlign='right';ctx.fillText(num(hi-f*(hi-lo),1),box.x-7,y+3);ctx.textAlign='center';ctx.fillText(num(f*end,options.xDecimals??1),tx(f*end),box.y+box.h+17);}
  for(const s of series) {ctx.strokeStyle=s.color;ctx.lineWidth=s.width||2;ctx.setLineDash(s.dashed?[6,4]:[]);ctx.beginPath();let connected=false;s.values.forEach((v,i)=>{if(!Number.isFinite(v)){connected=false;return;}if(connected)ctx.lineTo(tx(xs[i]),ty(v));else ctx.moveTo(tx(xs[i]),ty(v));connected=true;});ctx.stroke();ctx.setLineDash([]);
    if(options.frame!==undefined&&Number.isFinite(s.values[options.frame])){ctx.fillStyle=s.color;ctx.beginPath();ctx.arc(tx(xs[options.frame]),ty(s.values[options.frame]),4,0,2*Math.PI);ctx.fill();}}
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
  const series=Object.entries(colors).map(([key,color])=>({name:{center_c:'Central',max_c:'Máxima',mean_c:'Media',min_c:'Mínima'}[key],values:result.history[key],color}));
  const o=result.parameters;
  if(o.boundary_type==='dirichlet')series.push({name:`Dirichlet principal: ${o.boundary_c} °C`,values:result.time_s.map(()=>o.boundary_c),color:'#0891b2',dashed:true});
  if(o.bottom_type==='dirichlet')series.push({name:`Dirichlet base: ${o.bottom_c} °C`,values:result.time_s.map(()=>o.bottom_c),color:'#dc2626',dashed:true});
  return series;
}
function historyFrameAt(times,fraction) {
  const target=Math.max(0,Math.min(1,fraction))*times.at(-1);
  return times.reduce((best,t,i)=>Math.abs(t-target)<Math.abs(times[best]-target)?i:best,0);
}
function historyRange(history,index) {
  const min=history.min_c[index], max=history.max_c[index];
  return Number.isFinite(min)&&Number.isFinite(max)?{min,max,delta:max-min}:null;
}
function showPourPlan() {
  hiddenPourIds.clear();pourVisibilityVersion++;
  $('pour-visibility').classList.toggle('hidden',!data.pour_plan);
  $('pour-visibility-options').replaceChildren();
  $('pour-plan').classList.toggle('hidden',!data.pour_plan);
  $('pour-rows').replaceChildren();
  if(!data.pour_plan)return;
  const rows=data.pour_plan.layers;
  for(const row of rows){
    const label=document.createElement('label'),input=document.createElement('input');
    input.type='checkbox';input.checked=true;input.dataset.pourId=row.id;
    input.addEventListener('change',()=>{input.checked?hiddenPourIds.delete(row.id):hiddenPourIds.add(row.id);refreshPourVisibility();});
    label.append(input,document.createTextNode(`Vertida ${row.id}`));$('pour-visibility-options').append(label);
  }
  $('pour-visibility-caption').textContent='Todas seleccionadas. Solo cambia la vista 3D; los gráficos y el cálculo conservan todas las vertidas.';
  $('pour-summary').textContent=`${rows.length} capas de igual altura · volumen voxelizado total ${num(rows.reduce((s,r)=>s+r.voxel_volume_m3,0),2)} m³ · ${data.construction?'activación por cronograma':'todas presentes desde t = 0'}`;
  $('pour-scope').textContent=data.construction?'Colocación instantánea por capa. Las superficies temporales intercambian calor hasta recibir la siguiente capa. Fuente por edad local; balance con energía de colocación.':'División geométrica: cambiar solo su cantidad no altera las temperaturas.';
  for(const row of rows){
    const tr=document.createElement('tr');
    for(const value of [`Vertida ${row.id}`+(data.construction?` · día ${num(row.start_s/86400,2)} · ${num(row.placement_c,1)} °C`:''),num(row.z_min_m,3),num(row.z_max_m,3),num(row.cells,0),num(row.voxel_volume_m3,2)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}
    tr.firstChild.style.borderLeft=`5px solid rgb(${temperatureColor((row.id-.5)/rows.length,0,1).join(',')})`;
    $('pour-rows').append(tr);
  }
}
function pourColorsActive(){return !!data?.pour_plan&&$('model-color').value==='pours';}
function refreshPourVisibility() {
  pourVisibilityVersion++;
  const shown=data.pour_plan.layers.length-hiddenPourIds.size;
  $('pour-visibility-caption').textContent=`${shown} de ${data.pour_plan.layers.length} vertidas seleccionadas. Las aún no colocadas permanecen ocultas. Solo cambia la vista 3D; los gráficos y el cálculo conservan todas las vertidas.`;
  renderer.draw();
}
function modelValues(hiddenIds=new Set()){return data.frames_c[frame].map((t,i)=>t===null||hiddenIds.has(data.pour_plan?.cell_pour_id[i])?-1e20:pourColorsActive()?(data.pour_plan.cell_pour_id[i]-.5)/data.pour_plan.layers.length:t);}
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
  return {heights,series:frames.map((f,i)=>{const values=cells.map(j=>result.frames_c[f][j]);const bottomActive=values[0]!==null,topActive=values.at(-1)!==null;if(lower)values.unshift(bottomActive?result.parameters.bottom_c:null);if(upper)values.push(topActive?result.parameters.boundary_c:null);return {values,color:shades[i],width:f===current?3.5:1.7,dashed:f!==current,frame:f};})};
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
  if(data.construction)$('frame-caption').textContent+=` · ${data.frames_c[frame].filter(Number.isFinite).length} celdas colocadas`;
  if(data.construction)$('geometry-chip').textContent=`${data.frames_c[frame].filter(Number.isFinite).length} colocadas / ${data.stats.cells} celdas previstas`;
  if(data.dimension===3)renderer.draw();else if(data.dimension===2)heatmap('flat-canvas',true);else profile('flat-canvas',true);
  if(data.dimension===3)heatmap('slice-canvas');else profile('slice-canvas');
  const unit=days?86400:3600;
  const series=historySeries(data);
  lineChart('history-canvas',series,data.time_s.map(t=>t/unit),{cursor:data.time_s[frame]/unit,frame,xLabel:days?'Tiempo [días]':'Tiempo [h]'});
  $('history-caption').textContent=`${timeText(data.time_s[frame])} · interior central ${num(data.history.center_c[frame],2)} °C · pulsa el gráfico para recorrer el tiempo`;
  const range=historyRange(data.history,frame);
  $('history-range').textContent=range
    ?`Máxima ${num(range.max,2)} °C · Mínima ${num(range.min,2)} °C · ΔT ${num(range.delta,2)} °C`
    :'Diferencial pendiente hasta que haya hormigón activo.';
  $('history-legend').replaceChildren(...series.map(s=>{const item=document.createElement('span'),mark=document.createElement('i');mark.style.background=s.color;item.append(mark,document.createTextNode(s.name));return item;}));
  const profiles=heightProfiles(data,frame);
  lineChart('height-canvas',profiles.series,profiles.heights,{xLabel:'Altura [m]',xDecimals:2});
  $('height-caption').textContent=`Columna central · línea gruesa: ${timeText(data.time_s[frame])} · extremos Dirichlet incluidos cuando están prescritos`;
  $('height-legend').replaceChildren(...profiles.series.map(s=>{const item=document.createElement('span'),mark=document.createElement('i');mark.style.background=s.color;item.append(mark,document.createTextNode(timeText(data.time_s[s.frame])+(s.frame===frame?' · seleccionado':'')));return item;}));
  const source=data.source_curve;
  const sourceSeries=source.layers?source.layers.map((r,i)=>({values:r.rate_w_m3,color:['#2563eb','#ea580c','#8b5cf6','#0891b2'][i%4]})):[{values:source.rate_w_m3,color:'#ea580c'}];
  lineChart('source-canvas',sourceSeries,source.time_s.map(t=>t/unit),{cursor:data.time_s[frame]/unit,minY:Math.min(...source.rate_w_m3)>=0?0:undefined,xLabel:days?'Tiempo [días]':'Tiempo [h]',yLabel:'Q(t) [W/m³]'});
  const central=data.history.center_c.filter(Number.isFinite),peak=central.length?Math.max(...central):null;
  const zeroSource=source.rate_w_m3.every(q=>q===0);
  $('source-caption').textContent=(zeroSource?'Sin generación de calor: Q(t) = 0. Selecciona el pulso en Tipo de fuente y pulsa Calcular temperaturas. ':data.parameters.source_type==='cosine'?`Qmax ${num(data.parameters.qmax_w_m3,1)} W/m³ · τ ${num(data.parameters.source_duration_days,2)} días · `:`Fuente constante ${num(data.parameters.source_w_m3,1)} W/m³ · `)+`máximo central guardado: ${num(peak,2)} °C.`;
  if(data.construction)$('source-caption').textContent+=' Curvas por vertida en orden: '+data.pour_plan.layers.map((r,i)=>`${r.id} (${'azul,naranja,violeta,turquesa'.split(',')[i%4]})`).join(', ')+'.';
  if(data.construction&&data.parameters.activation_energy_j_mol>0)$('source-caption').textContent=`Potencia instantánea media por vertida · Ea ${num(data.parameters.activation_energy_j_mol,0)} J/mol · referencia 20 °C. Qmax = 1300 W/m³ a referencia; la potencia real incluye Arrhenius. Curvas: `+data.pour_plan.layers.map((r,i)=>`${r.id} (${'azul,naranja,violeta,turquesa'.split(',')[i%4]})`).join(', ')+'.';
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
    void main(){visible=(temperature< -1e10||(cutMode==1&&position.x>cut)||(cutMode==2&&position.z>cut))?0:1;
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
    const frameKey=`${frame}:${$('model-color').value}:${pourVisibilityVersion}`;
    if(this.lastFrame!==frameKey){gl.bindBuffer(gl.ARRAY_BUFFER,this.temperatureBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(modelValues(hiddenPourIds)),gl.DYNAMIC_DRAW);this.lastFrame=frameKey;}
    gl.drawArraysInstanced(gl.TRIANGLES,0,36,data.positions_m.length);
  }
  software(matrix,box,mode,cut) {
    // Respaldo sin GPU: proyecta centros superficiales del mismo campo calculado.
    const ctx=this.ctx;ctx.setTransform(box.dpr,0,0,box.dpr,0,0);ctx.clearRect(0,0,box.w,box.h);
    const visible=p=>mode==='full'||p[mode==='x'?0:2]<=cut;
    const [nx,ny,nz]=data.shape, entries=[];
    const keep=(i,j,k)=>{if(i<0||j<0||k<0||i>=nx||j>=ny||k>=nz)return false;const q=lookup[(i*ny+j)*nz+k];return q>=0&&data.frames_c[frame][q]!==null&&!hiddenPourIds.has(data.pour_plan?.cell_pour_id[q])&&visible(data.positions_m[q]);};
    for(let q=0;q<data.positions_m.length;q++) {
      const p=data.positions_m[q];if(data.frames_c[frame][q]===null||hiddenPourIds.has(data.pour_plan?.cell_pour_id[q])||!visible(p))continue;
      const flat=data.active_indices[q],i=Math.floor(flat/(ny*nz)),j=Math.floor(flat/nz)%ny,k=flat%nz;
      if(keep(i-1,j,k)&&keep(i+1,j,k)&&keep(i,j-1,k)&&keep(i,j+1,k)&&keep(i,j,k-1)&&keep(i,j,k+1))continue;
      const v=p.map((x,a)=>(x-this.center[a])*2/this.maxLength), out=[0,0,0,0];
      for(let r=0;r<4;r++)out[r]=matrix[r]*v[0]+matrix[4+r]*v[1]+matrix[8+r]*v[2]+matrix[12+r];
      if(out[3]<=0)continue;
      entries.push({x:(out[0]/out[3]+1)*box.w/2,y:(1-out[1]/out[3])*box.h/2,z:out[2]/out[3],q,size:Math.max(2,box.h*data.spacing_m[0]/this.maxLength/out[3]*2.5)});
    }
    entries.sort((a,b)=>b.z-a.z);
    const values=modelValues(hiddenPourIds),layers=pourColorsActive();
    for(const p of entries){ctx.fillStyle=`rgb(${temperatureColor(values[p.q],layers?0:data.colorLow,layers?1:data.colorHigh).join(',')})`;ctx.fillRect(p.x-p.size/2,p.y-p.size/2,p.size,p.size);}
  }
}
let renderer;
function updateClip(){const open=$('view-mode').value!=='full'&&data?.dimension===3;$('clip-control').classList.toggle('hidden',!open);$('clip-caption').textContent=$('clip-slider').value+' %';if(renderer&&data?.dimension===3)renderer.draw();}

form.addEventListener('submit',calculate);
$('model-color').addEventListener('change',draw);
for(const [id,hide] of [['show-all-pours',false],['hide-all-pours',true]])$(id).addEventListener('click',()=>{
  if(!data?.pour_plan)return;
  hiddenPourIds.clear();if(hide)for(const row of data.pour_plan.layers)hiddenPourIds.add(row.id);
  for(const input of $('pour-visibility-options').querySelectorAll('input'))input.checked=!hide;
  refreshPourVisibility();
});
const tabNames = ['laboratory', 'project', 'terrain', 'weather', 'monte-carlo', 'plans'];
const mcMetrics = [
  {key:'tmax_c', label:'Temperatura máxima', short:'T máx', limit:70},
  {key:'delta_t_max_c', label:'Diferencial máximo', short:'ΔT máx', limit:20}
];
const emptyMonteCarlo = () => ({hash:null,summary:null,runs:new Map()});
let mcLot = emptyMonteCarlo(), mcLoad = 0, mcExample = false;

function mergeMonteCarlo(lot, documents) {
  const next={...lot, runs:new Map(lot.runs)};
  const finite=Number.isFinite;
  for(const {name, data:d} of documents){
    const invalid=()=>{throw Error(`${name}: formato de resultado Monte Carlo inválido.`);};
    if(typeof d?.manifest_sha256!=='string'||!/^[a-f0-9]{64}$/.test(d.manifest_sha256))invalid();
    if(next.hash&&next.hash!==d.manifest_sha256)throw Error(`${name}: pertenece a otro lote. Pulsa Limpiar lote para cambiar de lote.`);
    next.hash=d.manifest_sha256;
    if('samples' in d){
      if(!Number.isSafeInteger(d.samples)||d.samples<1)invalid();
      const countOk=count=>Number.isSafeInteger(count)&&count>=0&&count<=d.samples;
      if(!countOk(d.any_exceedances))invalid();
      for(const {key} of mcMetrics){
        const s=d[key], p=s?.percentiles_c;
        if(![s?.threshold_c,s?.mean_c,p?.p05,p?.p50,p?.p95].every(finite)||
           !countOk(s.exceedances)||s.exceedances>d.any_exceedances||p.p05>p.p50||p.p50>p.p95)invalid();
      }
      next.summary=d;
    }else{
      if(!Number.isSafeInteger(d.sample_id)||d.sample_id<0||
        !['placement_c','theta_inf_c','tau_h'].every(key=>finite(d.parameters?.[key]))||
        !mcMetrics.every(({key})=>finite(d.metrics?.[key])))invalid();
      next.runs.set(d.sample_id,d);
    }
  }
  if(next.summary&&Array.from(next.runs.keys()).some(id=>id>=next.summary.samples))
    throw Error('Hay corridas con índices fuera del tamaño declarado por aggregate.json.');
  return next;
}

function monteCarloRow(body,values) {
  const row=document.createElement('tr');
  for(const value of values){
    const cell=document.createElement('td');
    if(typeof value==='string')cell.textContent=value;else cell.append(value);
    row.append(cell);
  }
  body.append(row);
}

function drawMonteCarlo() {
  const {hash,summary,runs}=mcLot;
  $('mc-clear').disabled=!hash;
  $('mc-summary').classList.toggle('hidden',!summary);
  $('mc-runs').classList.toggle('hidden',!runs.size);
  $('mc-status').textContent=hash
    ?`Lote ${hash.slice(0,12)} · ${summary?`${summary.samples} simulaciones`:'resumen pendiente'} · ${runs.size} corridas cargadas`
    :'Selecciona los archivos del lote.';
  const summaryRows=$('mc-summary-rows');
  summaryRows.replaceChildren();
  if(summary){
    const frequency=count=>{
      const group=document.createElement('span'), meter=document.createElement('meter');
      group.className='mc-fraction';meter.max=summary.samples;meter.value=count;meter.setAttribute('aria-hidden','true');
      group.append(meter,`${count}/${summary.samples} · ${num(100*count/summary.samples,1)} %`);
      return group;
    };
    for(const {key,label} of mcMetrics){
      const stat=summary[key];
      monteCarloRow(summaryRows,[`${label} > ${num(stat.threshold_c,0)} °C`,frequency(stat.exceedances),
        ...[stat.mean_c,stat.percentiles_c.p05,stat.percentiles_c.p50,stat.percentiles_c.p95].map(v=>`${num(v,2)} °C`)]);
    }
    monteCarloRow(summaryRows,['Cualquiera de los dos',frequency(summary.any_exceedances),'—','—','—','—']);
  }
  const filter=$('mc-filter').value, runRows=$('mc-run-rows');
  runRows.replaceChildren();
  let visible=0;
  for(const row of Array.from(runs.values()).sort((a,b)=>a.sample_id-b.sample_id)){
    const failed=mcMetrics.filter(({key,limit})=>row.metrics[key]>(summary?.[key].threshold_c??limit));
    if(filter!=='all'&&!(filter==='any'?failed.length:filter==='pass'?!failed.length:failed.some(m=>m.key===filter)))continue;
    visible++;
    const status=document.createElement('span');
    status.classList.toggle('mc-exceeds',failed.length>0);
    status.textContent=failed.map(m=>m.short).join(' y ')||'Ninguno';
    monteCarloRow(runRows,[String(row.sample_id),...['placement_c','theta_inf_c','tau_h'].map(key=>num(row.parameters[key],2)),
      ...mcMetrics.map(({key})=>num(row.metrics[key],2)),status]);
  }
  $('mc-run-count').textContent=`${visible} de ${runs.size} cargadas${summary?' · '+summary.samples+' en el lote':' · umbrales E12 de 70 °C y 20 °C'}`;
}

$('mc-files').addEventListener('change',async event=>{
  const files=Array.from(event.target.files), revision=++mcLoad;
  if(!files.length)return;
  event.target.value='';
  const error=$('mc-error');
  error.classList.add('hidden');
  try{
    const documents=await Promise.all(files.map(async file=>{
      try{return {name:file.name,data:JSON.parse(await file.text())};}
      catch{throw Error(`${file.name}: no se pudo leer como JSON.`);}
    }));
    if(revision!==mcLoad)return;
    mcLot=mergeMonteCarlo(mcExample?emptyMonteCarlo():mcLot,documents);
    mcExample=false;
    $('mc-example-note').classList.add('hidden');
    drawMonteCarlo();
  }catch(problem){
    if(revision!==mcLoad)return;
    error.textContent=problem.message;
    error.classList.remove('hidden');
  }
});
$('mc-filter').addEventListener('change',drawMonteCarlo);
$('mc-clear').addEventListener('click',()=>{
  mcLoad++;
  mcLot=emptyMonteCarlo();
  mcExample=false;
  $('mc-example-note').classList.add('hidden');
  $('mc-filter').value='all';
  $('mc-error').classList.add('hidden');
  drawMonteCarlo();
});
const e11Planes = {xz:[0,2,1], yz:[1,2,0], xy:[0,1,2]};
const e11Curves = [
  ['núcleo','#dc2626'], ['superficie superior','#ea580c'], ['superficie lateral','#7c3aed'],
  ['tmax_c','#172033','Máxima del hormigón'], ['aire_c','#2563eb','Aire a 2 m']
];
let e11;

class E11SurfaceView {
  constructor(canvas) {
    this.canvas = canvas;
    this.reset();
    let drag;
    canvas.addEventListener('pointerdown', event=>{
      if(event.button!==0)return;
      drag=[event.clientX,event.clientY];canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event=>{
      if(!drag)return;
      this.yaw+=(event.clientX-drag[0])*.009;
      this.pitch=Math.max(.12,Math.min(1.52,this.pitch+(event.clientY-drag[1])*.009));
      drag=[event.clientX,event.clientY];this.schedule();
    });
    canvas.addEventListener('lostpointercapture', ()=>{drag=null;});
    canvas.addEventListener('wheel', event=>{
      event.preventDefault();
      this.zoom=Math.max(.6,Math.min(4,this.zoom*Math.exp(-event.deltaY*.001)));
      this.schedule();
    },{passive:false});
  }
  reset() {
    this.yaw=-.6;this.pitch=.72;this.zoom=1;
    this.schedule();
  }
  schedule() {
    if(this.pending)return;
    this.pending=requestAnimationFrame(()=>{
      this.pending=null;
      if(e11?.mesh_3d&&!$('panel-weather').classList.contains('hidden'))this.draw(e11,e11Current(),$('e11-soil').checked);
    });
  }
  draw(result,index,soil) {
    const {ctx,w,h}=context2d(this.canvas.id);
    if(!w||!h)return;
    const lengths=result.shape.map((n,i)=>n*result.spacing_m[i]);
    const center=result.origin_m.map((x,i)=>x+lengths[i]/2);
    const scale=Math.min(w,h)*.70*this.zoom/Math.max(...lengths);
    const cos=Math.cos(this.yaw),sin=Math.sin(this.yaw),p=Math.sin(this.pitch),q=Math.cos(this.pitch);
    const faces=[];
    for(const surface of result.mesh_3d.surfaces){
      if(surface.material===2&&!soil)continue;
      const points=surface.points_m.map(([x,y,z])=>{
        x-=center[0];y-=center[1];z-=center[2];
        const depth=sin*x+cos*y;
        return [w/2+(cos*x-sin*y)*scale,h/2+(depth*p-z*q)*scale,depth*q+z*p];
      });
      surface.triangles.forEach(([a,b,c],i)=>{
        const u=points[a],v=points[b],s=points[c];
        faces.push({u,v,s,depth:u[2]+v[2]+s[2],cell:surface.frame_indices[i]});
      });
    }
    faces.sort((a,b)=>a.depth-b.depth);
    const temperatures=result.frames_c[index], colors=new Map();
    ctx.lineWidth=.55;
    for(const {u,v,s,cell} of faces){
      if(!colors.has(cell))colors.set(cell,`rgb(${temperatureColor(temperatures[cell],result.low,result.high).join(',')})`);
      ctx.fillStyle=ctx.strokeStyle=colors.get(cell);
      ctx.beginPath();ctx.moveTo(u[0],u[1]);ctx.lineTo(v[0],v[1]);ctx.lineTo(s[0],s[1]);ctx.closePath();ctx.fill();ctx.stroke();
    }
  }
}
let e11SurfaceView;

function validateE11(result) {
  const invalid = () => {throw Error('Archivo E11 inválido. Selecciona el visor_e11.json generado por weather_3d.');};
  const vector = (a,n) => Array.isArray(a)&&a.length===n&&a.every(Number.isFinite);
  const times = a => Array.isArray(a)&&a.length>0&&a[0]===0&&a.every((v,i)=>Number.isFinite(v)&&(!i||v>a[i-1]));
  if(result?.format!=='mcoc-e11-v1'||!vector(result.shape,3)||!result.shape.every(n=>Number.isInteger(n)&&n>0)||
    !vector(result.spacing_m,3)||result.spacing_m.some(x=>x<=0)||!vector(result.origin_m,3))invalid();
  const size=result.shape.reduce((a,b)=>a*b);
  const ids=result.active_indices, count=ids?.length;
  if(size>2000000||!Array.isArray(ids)||!count||
    ids.some((id,i)=>!Number.isInteger(id)||id<0||id>=size||(i&&id<=ids[i-1]))||
    !vector(result.material,count)||result.material.some(v=>v!==1&&v!==2))invalid();
  if(!times(result.times_h)||!Array.isArray(result.frames_c)||result.frames_c.length!==result.times_h.length||
    !times(result.history?.t_h)||result.history.t_h.length>20000)invalid();
  const sampleCount=result.history.t_h.length;
  if(e11Curves.some(([key])=>!vector(result.history[key],sampleCount))||
    !vector(result.wind_m_s,sampleCount)||!vector(result.solar_w_m2,sampleCount))invalid();
  if(result.boundary_frames!==undefined&&(!Array.isArray(result.boundary_frames)||
    result.boundary_frames.length!==result.times_h.length||result.boundary_frames.some(frame=>
      !['air_c','wind_m_s','solar_w_m2','h_w_m2k','top_sol_air_c','side_sol_air_c'].every(key=>Number.isFinite(frame?.[key])))))invalid();
  if(result.mesh_3d!==undefined){
    const mesh=result.mesh_3d;
    if(typeof mesh?.engine!=='string'||!Array.isArray(mesh.surfaces)||!mesh.surfaces.length)invalid();
    for(const surface of mesh.surfaces){
      if(![1,2].includes(surface?.material)||!Array.isArray(surface.points_m)||!surface.points_m.every(p=>vector(p,3))||
        !Array.isArray(surface.triangles)||!vector(surface.frame_indices,surface.triangles.length))invalid();
      if(surface.triangles.some(t=>!vector(t,3)||!t.every(i=>Number.isInteger(i)&&i>=0&&i<surface.points_m.length))||
        surface.frame_indices.some(i=>!Number.isInteger(i)||result.material[i]!==surface.material))invalid();
    }
  }
  const cell = c => vector(c,3)&&c.every((n,i)=>Number.isInteger(n)&&n>=0&&n<result.shape[i]);
  const summary=result.summary;
  if(!cell(summary?.core?.cell)||!Array.isArray(summary.tmax_by_frame)||summary.tmax_by_frame.length!==result.times_h.length||
    summary.tmax_by_frame.some(s=>!cell(s?.cell)||!Number.isFinite(s.tmax_c))||typeof summary.weather?.status!=='string'||
    !['superior','lateral'].every(key=>cell(summary.surface_probes?.[key]?.cell))||
    !Number.isFinite(summary.max_core_minus_surface_c))invalid();
  let low=Infinity, high=-Infinity;
  for(const row of result.frames_c){
    if(!vector(row,count))invalid();
    for(const t of row){low=Math.min(low,t);high=Math.max(high,t);}
  }
  if(high-low<0.01){low-=0.5;high+=0.5;}
  const lookup=new Int32Array(size).fill(-1);
  ids.forEach((id,i)=>lookup[id]=i);
  return {...result, lookup, low, high};
}

function e11Current() {return Number($('e11-time').value);}

function e11SetPlane(cell) {
  const axis=e11Planes[$('e11-plane').value][2];
  $('e11-position').max=e11.shape[axis]-1;
  $('e11-position').value=cell[axis];
  drawE11();
}

function e11DrawSlice(index) {
  const [u,v,axis]=e11Planes[$('e11-plane').value], fixed=Number($('e11-position').value);
  const {ctx,w,h}=context2d('e11-map'), {shape,spacing_m:spacing,origin_m:origin}=e11;
  if(w<60||h<60)return;
  const scale=Math.min((w-54)/(shape[u]*spacing[u]),(h-42)/(shape[v]*spacing[v]));
  const dx=spacing[u]*scale, dy=spacing[v]*scale;
  const x0=(w-shape[u]*dx)/2, y0=(h+shape[v]*dy)/2-4;
  const field=e11.frames_c[index], showSoil=$('e11-soil').checked;
  const cell=[0,0,0];cell[axis]=fixed;
  for(let a=0;a<shape[u];a++)for(let b=0;b<shape[v];b++){
    cell[u]=a;cell[v]=b;
    const q=e11.lookup[(cell[0]*shape[1]+cell[1])*shape[2]+cell[2]];
    if(q<0||(!showSoil&&e11.material[q]===2))continue;
    ctx.fillStyle=`rgb(${temperatureColor(field[q],e11.low,e11.high).join(',')})`;
    ctx.fillRect(x0+a*dx,y0-(b+1)*dy,dx+0.2,dy+0.2);
  }
  const probes=e11.summary.surface_probes;
  for(const [probe,color,radius] of [[e11.summary.core.cell,'#fff',7],
    [e11.summary.tmax_by_frame[index].cell,'#22d3ee',4],
    [probes.superior.cell,'#fba24c',4],[probes.lateral.cell,'#c4a6ff',4]]){
    if(probe[axis]!==fixed)continue;
    const x=x0+(probe[u]+0.5)*dx, y=y0-(probe[v]+0.5)*dy;
    ctx.strokeStyle='#142337';ctx.lineWidth=4;ctx.beginPath();ctx.arc(x,y,radius,0,2*Math.PI);ctx.stroke();
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
  }
  ctx.fillStyle='#62738b';ctx.font='12px system-ui, sans-serif';ctx.textAlign='center';
  ctx.fillText(`${'XYZ'[u]} [m] · ${num(origin[u],2)} a ${num(origin[u]+shape[u]*spacing[u],2)}`,w/2,h-5);
  ctx.save();ctx.translate(12,h/2);ctx.rotate(-Math.PI/2);
  ctx.fillText(`${'XYZ'[v]} [m] · ${num(origin[v],2)} a ${num(origin[v]+shape[v]*spacing[v],2)}`,0,0);ctx.restore();
  $('e11-position-label').textContent=`${'XYZ'[axis]} = ${num(origin[axis]+(fixed+0.5)*spacing[axis],2)} m`;
}

function drawE11() {
  if(!e11||$('panel-weather').classList.contains('hidden'))return;
  const index=e11Current(), time=e11.times_h[index], hot=e11.summary.tmax_by_frame[index];
  $('e11-time-label').textContent=`${num(time,2)} h`;
  const start=Date.parse(e11.summary.simulation?.start_utc);
  $('e11-weather-time').textContent=Number.isFinite(start)
    ?new Date(start+time*3600000).toISOString().replace('T',' ').slice(0,16)+' UTC'
    :`${num(time,2)} h desde el inicio`;
  const boundary=e11.boundary_frames?.[index];
  const labels=boundary?[['Aire',boundary.air_c,'°C'],['Viento a 10 m',boundary.wind_m_s,'m/s'],
    ['Onda corta',boundary.solar_w_m2,'W/m²'],['h convectivo',boundary.h_w_m2k,'W/(m²·K)'],
    ['Sol-aire superior',boundary.top_sol_air_c,'°C'],['Sol-aire lateral',boundary.side_sol_air_c,'°C']]:[];
  $('e11-weather-values').textContent=labels.length?labels.map(([name,value,unit])=>`${name} ${num(value,2)} ${unit}`).join(' · ')
    :'El archivo incluye las curvas meteorológicas debajo del corte.';
  e11SurfaceView?.schedule();
  $('e11-cut-details').textContent=`Máxima del hormigón ${num(hot.tmax_c,2)} °C en el estado guardado.`;
  $('e11-field-note').textContent=`Escala fija ${num(e11.low,1)} a ${num(e11.high,1)} °C · blanco: núcleo · cian: punto caliente · naranja y violeta: sondas superficiales del corte.`;
  e11DrawSlice(index);
  const xs=e11.history.t_h, options={cursor:time,xLabel:'Tiempo [h]'};
  lineChart('e11-temperatures',e11Curves.map(([key,color])=>({values:e11.history[key],color,dashed:key==='tmax_c'})),xs,options);
  lineChart('e11-wind',[{values:e11.wind_m_s,color:'#168253'}],xs,{...options,minY:0,yLabel:'Viento [m/s]'});
  lineChart('e11-solar',[{values:e11.solar_w_m2,color:'#c87c08'}],xs,{...options,minY:0,yLabel:'Onda corta [W/m²]'});
}

function showE11(result, example=false) {
    e11=validateE11(result);
    const weather=e11.summary.weather, simulation=e11.summary.simulation;
    $('e11-source').textContent=`${example?'Ejemplo guardado · ':''}${weather.status} · ${num(e11.times_h.at(-1),2)} h · ${e11.shape.join(' × ')} celdas`;
    $('e11-provenance').textContent=[weather.folder,simulation?.start_utc&&`Inicio ${simulation.start_utc}`,
      weather.retrieved_at&&`Descarga ${weather.retrieved_at}`,weather.sha256&&`SHA-256 clima ${weather.sha256}`,
      simulation?.ifc_sha256&&`SHA-256 IFC ${simulation.ifc_sha256}`].filter(Boolean).join(' · ');
    $('e11-differential').textContent=`Mayor diferencia guardada del núcleo respecto de la sonda superficial más fría: ${num(e11.summary.max_core_minus_surface_c,2)} °C.`;
    $('e11-temperature-legend').replaceChildren(...e11Curves.map(([key,color,label])=>{
      const item=document.createElement('span'),mark=document.createElement('i');
      mark.style.background=color;item.append(mark,document.createTextNode(label||key));return item;
    }));
    $('e11-time').max=e11.times_h.length-1;$('e11-time').value=e11.times_h.length-1;
    $('e11-model').classList.toggle('hidden',!e11.mesh_3d);
    if(e11.mesh_3d){
      e11SurfaceView ??= new E11SurfaceView($('e11-model-canvas'));
      e11SurfaceView.reset();
      $('e11-model-source').textContent=`Malla de ${e11.mesh_3d.engine} · arrastra para girar y usa la rueda para acercar.`;
      $('e11-model-legend').textContent=`Escala fija ${num(e11.low,1)} a ${num(e11.high,1)} °C. La opción Mostrar suelo controla también esta vista.`;
    }
    $('e11-results').classList.remove('hidden');e11SetPlane(e11.summary.core.cell);
}

$('e11-file').addEventListener('change',async event=>{
  const file=event.target.files[0];
  if(!file)return;
  try{
    if(file.size>96*1024*1024)throw Error('El resultado supera 96 MB. Exporta menos cuadros o usa una malla más gruesa.');
    const result=JSON.parse(await file.text());
    if(event.target.files[0]!==file)return;
    showE11(result);
  }catch(error){
    if(event.target.files[0]!==file)return;
    e11=null;$('e11-results').classList.add('hidden');$('e11-provenance').textContent='';
    $('e11-source').textContent=error.message;
  }
});
for(const id of ['e11-time','e11-position','e11-soil'])$(id).addEventListener('input',drawE11);
$('e11-plane').addEventListener('change',()=>{if(e11)e11SetPlane(e11.summary.core.cell);});
$('e11-hot').addEventListener('click',()=>{if(e11)e11SetPlane(e11.summary.tmax_by_frame[e11Current()].cell);});
$('e11-camera-reset').addEventListener('click',()=>e11SurfaceView?.reset());
for(const id of ['e11-temperatures','e11-wind','e11-solar'])$(id).addEventListener('click',event=>{
  if(!e11)return;
  const rect=event.currentTarget.getBoundingClientRect();
  $('e11-time').value=historyFrameAt(e11.times_h,(event.clientX-rect.left-48)/(rect.width-67));
  drawE11();
});

function bindPythonJob(id, kind, inputs, render) {
  const jobForm=$(id), fields=jobForm.querySelector('fieldset'), message=jobForm.querySelector('[role="status"]');
  const snapshot=fields.elements.namedItem('snapshot');
  const pyvista=fields.elements.namedItem('pyvista');
  let ready=false, loading=false;
  jobForm.classList.remove('hidden');
  jobForm.addEventListener('submit',async event=>{
    event.preventDefault();
    if(fields.disabled)return;
    const data=new FormData(jobForm);
    const payload={kind,snapshot:data.get('snapshot'),coarsen:Number(data.get('coarsen'))};
    for(const name of inputs)payload[name]=Number(data.get(name));
    if(pyvista)payload.pyvista=pyvista.checked;
    fields.disabled=true;
    message.textContent='Iniciando el cálculo…';
    try{
      let job=await request('/api/jobs',payload);
      const path=`/api/jobs/${job.id}`;
      while(job.state==='running'){
        message.textContent=kind==='monte_carlo'?`Simulaciones completas: ${job.completed} de ${job.total}.`:'Resolviendo el campo térmico con el clima seleccionado…';
        await new Promise(resolve=>setTimeout(resolve,1000));
        job=await request(path);
      }
      if(job.state!=='done')throw Error(job.error||'El cálculo no terminó.');
      render(await request(path+'/result'));
      message.textContent=`Cálculo completo · archivos en ${job.folder}`;
    }catch(error){message.textContent=error.message;}
    finally{fields.disabled=false;}
  });
  return async()=>{
    if(ready||loading)return;
    loading=true;
    try{
      const available=await request('/api/jobs/options');
      const choices=available.snapshots.map(source=>new Option(source.id,source.id));
      snapshot.replaceChildren(...choices,new Option('Serie sintética','synthetic'));
      if(pyvista){
        pyvista.disabled=!available.pyvista;
        pyvista.checked=available.pyvista;
        if(!available.pyvista)pyvista.parentElement.append(' · complemento no instalado');
      }
      fields.disabled=false;
      message.textContent='';
      ready=true;
    }catch(error){message.textContent=`No se pudo consultar el servidor Python. ${error.message}`;}
    finally{loading=false;}
  };
}

function showMonteCarlo(result, example=false){
  mcLot=mergeMonteCarlo(emptyMonteCarlo(),[
    {name:'aggregate.json',data:result.summary},...result.runs.map(data=>({name:`Muestra ${data.sample_id}`,data}))]);
  mcLoad++;
  mcExample=example;
  const note=$('mc-example-note');
  note.classList.toggle('hidden',!example);
  if(example){
    const {seed,hours,snapshot}=result.source;
    note.textContent=`Ejemplo guardado · semilla ${seed} · ${hours/24} días por muestra · pronóstico ${snapshot} · rangos docentes.`;
  }
  $('mc-error').classList.add('hidden');
  $('mc-filter').value='all';
  drawMonteCarlo();
}

async function readDashboardExample(section){
  if(!portable)return request('/api/examples/'+section);
  const element=$('mcoc-example-'+section);
  if(!element)throw Error('Genera la campaña y vuelve a exportar el visor.');
  const encoded=element.textContent.trim();
  const bytes=Uint8Array.from(atob(encoded),char=>char.charCodeAt(0));
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).json();
}

const exampleRequests=new Set();
async function showDashboardExample(section){
  if(!['weather','monte-carlo'].includes(section)||exampleRequests.has(section))return;
  exampleRequests.add(section);
  try{
    const result=await readDashboardExample(section);
    if(section==='weather'&&!e11)showE11(result,true);
    if(section==='monte-carlo'&&!mcLot.hash&&!mcLoad)showMonteCarlo(result,true);
  }catch(error){
    exampleRequests.delete(section);
    if(section==='weather'&&!e11)$('e11-source').textContent='No se pudo cargar el ejemplo. '+error.message;
    if(section==='monte-carlo'&&!mcLot.hash)$('mc-status').textContent='No se pudo cargar el ejemplo. '+error.message;
  }
}

let plansCampaign, plansLoading=false;
const percent=value=>`${num(value*100,1)} %`;
function drawPlansMC(){
  const period=$('plans-mc-period').value;
  const rows=$('plans-mc-rows');
  rows.replaceChildren();
  const risk=value=>`${value.failures}/${value.n} · ${percent(value.p)} [${value.ci95.map(percent).join('–')}]`;
  for(const plan of plansCampaign.plans){
    const row=plan.statistics[period];
    monteCarloRow(rows,[plan.id,num(plan.duration_h,2),num(row.tmax.p95,2),num(row.delta.p95,2),
      risk(row.tmax),risk(row.delta),risk(row.joint),row.open_horizons??'—',
      plan.feasible?'Cumple en el lote':'Sin cumplimiento demostrado']);
  }
}

function drawPlanScenarios(){
  if(!plansCampaign)return;
  const plan=plansCampaign.plans.find(row=>row.id===$('plan-choice').value);
  const stagedBlanket=stages=>stages.map(([hour,thickness])=>
    `${num(hour/24,1)} d → ${num(thickness*1000,2)} mm`).join(' / ');
  const protection=plan.blanket_stages
    ? ` · ${plan.blanket_core_stages?'perímetro y costados':'manta superior y lateral'} · ${stagedBlanket(plan.blanket_stages)}`+
      (plan.blanket_core_stages?` · cubierta central · ${stagedBlanket(plan.blanket_core_stages)}`:'')+
      ` · R de subbase ${num(plan.subbase_r_m2k_w??0,2)} m²·K/W`
    : ` · retiro de manta superior ${num(plan.top_remove_h,0)} h`+
      (plan.side_blanket?` · manta lateral ${num((plan.side_blanket_m??0.025)*1000,0)} mm`:'');
  $('plan-schedule').textContent=plan.schedule.map(pour=>
    `V${pour.layer} · ${num(pour.start_h,2)}–${num(pour.finish_h,2)} h · ${num(pour.volume_m3,1)} m³`).join('  |  ')+
    ` · colocación a ${num(plan.placement_c??plansCampaign.config.placement_c,1)} °C · desmolde ${num(plan.strip_h,0)} h`+protection;
  $('plan-weather-checks').textContent=Object.entries(plan.climate_sensitivity??{}).map(([label,row])=>
    `${label} · ${row.failures}/${row.runs} fallas · T máx ${num(row.max_t_c,2)} °C · ΔT máx ${num(row.max_delta_c,2)} °C`).join(' | ');
  const rows=$('plan-scenarios');rows.replaceChildren();
  const xyz=point=>point.xyz_m.map(value=>num(value,3)).join(' / ');
  for(const scenario of plansCampaign.scenarios.filter(row=>row.plan===plan.id)){
    monteCarloRow(rows,[scenario.curve,scenario.climate.id,percent(scenario.weight),num(scenario.tmax.value_c,2),
      num(scenario.tmax.time_h,2),xyz(scenario.tmax),num(scenario.baseline.delta.value_c,2),
      num(scenario.delta.value_c,2),num(scenario.delta.time_h,2),
      xyz(scenario.delta.surface),`${num(scenario.hours,0)}${scenario.horizon_open?' · abierto':''}`,
      num(scenario.hours-plan.duration_h,2),
      num(scenario.weather_hours[scenario.climate.tail_method??'persistencia']??0,0),scenario.fails?'Sí':'No']);
  }
}

function showPlans(bundle){
  const campaign=bundle.campaign;
  $('plans-figures').replaceChildren(...Object.entries(bundle.figures||{}).map(([label,data])=>{
    const figure=document.createElement('figure'), img=document.createElement('img');
    figure.className='card plans-figure';
    img.alt=label;
    img.loading='lazy';
    img.src='data:image/png;base64,'+data;
    const caption=document.createElement('figcaption');
    caption.textContent=label;
    figure.append(img,caption);
    return figure;
  }));
  if(campaign?.format==='mcoc-monte-carlo-v1'&&Array.isArray(campaign.plans)&&campaign.plans.length){
    plansCampaign=campaign;
    $('plans-results').classList.add('hidden');
    $('plans-mc-results').classList.remove('hidden');
    $('plans-status').textContent=campaign.selected
      ? `Plan ${campaign.selected}: cumple en el lote ${campaign.phase==='confirm'?'de confirmación':'evaluado'}.`
      : `Sin plan factible demostrado. Mejor alternativa relativa: ${campaign.best_relative}.`;
    $('plans-mc-label').textContent=`Semilla ${campaign.seed} · ${campaign.weather_members.length} miembros · ${campaign.common_forecast_hours} h de pronóstico común`;
    drawPlansMC();
    return;
  }
  if(campaign?.format!=='mcoc-final-v1'||!Array.isArray(campaign.plans)||!campaign.plans.length||
    !Array.isArray(campaign.scenarios))throw Error('El archivo no contiene una comparación G8.');
  $('plans-mc-results').classList.add('hidden');
  const rows=$('plans-rows');rows.replaceChildren();
  for(const plan of campaign.plans){
    const primary=campaign.scenarios.filter(row=>row.plan===plan.id&&row.weight>0);
    const baseline=Math.max(...primary.map(row=>row.baseline.delta.value_c));
    monteCarloRow(rows,[`${plan.id} · ${plan.label}`,num(plan.duration_h,2),num(baseline,2),
      num(plan.max_delta_c,2),percent(plan.prob_tmax),
      percent(plan.prob_delta),percent(plan.prob_joint_14d),percent(plan.prob_joint),percent(plan.prob_joint_all_curves),
      plan.id===campaign.selected?'Seleccionado':plan.feasible?'Factible':plan.classification_closed?'Supera 5 %':'Horizonte abierto']);
  }
  const {config}=campaign;
  $('plans-assumptions').textContent=`t₀ ${config.start_local} · ${config.pump_count} bomba(s) · ${config.flow_m3_h_per_pump} m³/h por bomba · espera mínima ${config.minimum_wait_h} h · colocación a ${num(config.placement_c,1)} °C.`;
  $('plans-status').textContent=(campaign.selected?`Plan ${campaign.selected}: menor duración entre los factibles.`:
    'La campaña no identificó un plan factible.')+` ${campaign.scenarios.length} combinaciones de plan, hidratación y clima evaluadas.`;
  const selector=$('plan-choice');
  selector.replaceChildren(...campaign.plans.map(plan=>new Option(`${plan.id} · ${plan.label}`,plan.id)));
  selector.value=campaign.selected||campaign.plans.reduce((a,b)=>a.max_delta_c<=b.max_delta_c?a:b).id;
  const evidence=campaign.verification;
  $('plans-verification').classList.toggle('hidden',!evidence);
  $('plans-verification-rows').replaceChildren();
  $('plans-protection-rows').replaceChildren();
  $('plans-protection-details').classList.toggle('hidden',!evidence?.metrics.combined);
  if(evidence){
    const profiles=[];
    $('plans-verification-caption').textContent='Escenario de mayor diferencial para cada plan mostrado.';
    for(const check of [evidence,...(evidence.additional_cases??[])]){
      for(const [key,row] of Object.entries(check.metrics)){
        const label={base:'Base',spatial:'Malla refinada',temporal:'Paso reducido',combined:'Malla y paso refinados'}[key];
        monteCarloRow($('plans-verification-rows'),[`${check.candidate} · ${check.scenario.curve} · ${check.scenario.climate}`,label,
          row.grid_spacing_m.map(v=>num(v,3)).join(' × '),num(row.dt,0),
          num(row.tmax_c,2),num(row.delta_c,2),row.delta_face?`${num(row.delta_h,2)} h · ${row.delta_face}`:'—',
          row.energy_error_relative.toExponential(2)]);
      }
      const refined=check.metrics.combined;
      if(!refined)continue;
      for(const row of refined.protection_samples){
        monteCarloRow($('plans-protection-rows'),[check.candidate,num(row.time_h,2),row.face,num(row.tmax_c,2),
          num(row.surface_c,2),num(row.delta_c,2)]);
      }
      profiles.push(`${check.candidate} (${refined.delta_face}): `+
        refined.profile_mm_c.map(([depth,temp])=>`${num(depth,1)} mm → ${num(temp,2)} °C`).join(', '));
    }
    $('plans-depth-profiles').textContent='Perfil normal al máximo diferencial con malla y paso refinados. '+profiles.join(' · ');
  }
  plansCampaign=campaign;
  $('plans-results').classList.remove('hidden');
  drawPlanScenarios();
}

async function openDefaultPlans(){
  if(plansCampaign||plansLoading)return;
  plansLoading=true;
  try{
    const bundle=await readDashboardExample('plans');
    if(!plansCampaign)showPlans(bundle);
  }catch(error){$('plans-status').textContent='La campaña aún no está disponible. '+error.message;}
  finally{plansLoading=false;}
}
$('plan-choice').addEventListener('change',drawPlanScenarios);
$('plans-mc-period').addEventListener('change',drawPlansMC);
$('plans-file').addEventListener('change',async event=>{
  const file=event.target.files[0];
  if(!file)return;
  try{showPlans({campaign:JSON.parse(await file.text())});}
  catch(error){$('plans-status').textContent=error.message;}
});

const pythonJobTabs=portable?{}:{
  weather:bindPythonJob('e11-python','weather',['hours'],showE11),
  'monte-carlo':bindPythonJob('mc-python','monte_carlo',['count','seed','workers'],showMonteCarlo)
};
if(portable)for(const note of document.querySelectorAll('.portable-example-note'))note.classList.remove('hidden');
let terrainView, terrainLoading = false;

async function showTerrain() {
  if (terrainView) {
    terrainView.scheduleDraw();
    return;
  }
  if (terrainLoading) return;
  terrainLoading = true;
  const status = $('terrain-status');
  status.textContent = 'Preparando el relieve…';
  status.classList.remove('hidden');
  $('terrain-beacon').classList.add('hidden');
  try {
    const embedded = $('mcoc-terrain');
    let terrain;
    if (embedded) {
      terrain = JSON.parse(embedded.textContent);
    } else {
      const response = await fetch('/terrain_g8.json');
      if (!response.ok) throw Error('No se pudo cargar el recorte de Llanquihue.');
      terrain = await response.json();
    }
    $('terrain-location').textContent = `${terrain.latitude.toFixed(6)}, ${terrain.longitude.toFixed(6)} · Los Lagos`;
    const texture = $('mcoc-texture');
    let photo = new Image();
    photo.src = texture ? `data:image/jpeg;base64,${texture.textContent.trim()}` : '/terrain_g8.jpg';
    try {
      await photo.decode();
    } catch {
      photo = null;
    }
    const terrainMeta = meta || await request('/api/meta');
    terrainView = new TerrainView($('panel-terrain'), terrain, photo, terrainMeta.terrain_foundation);
    const imagery = photo ? ' · Sentinel-2 de 2016' : ' · textura satelital no disponible';
    const sideKm = num(terrain.extent_m / 1000, 0);
    $('terrain-details').textContent = `Recorte de ${sideKm} × ${sideKm} km · malla visual de ${terrainView.spacing} m · relieve regional ×3 y detalle a escala real · cota estimada ${num(terrainView.elevation, 1)} m${imagery}.`;
    status.classList.add('hidden');
    $('terrain-beacon').classList.remove('hidden');
  } catch (error) {
    status.textContent = error.message;
  } finally {
    terrainLoading = false;
  }
}

function selectTab(section) {
  for(const name of tabNames){
    const active=name===section;
    $('tab-'+name).setAttribute('aria-selected',String(active));$('tab-'+name).tabIndex=active?0:-1;
    $('panel-'+name).classList.toggle('hidden',!active);
  }
  if(section==='laboratory')requestAnimationFrame(draw);
  if(section==='terrain')void showTerrain();
  if(section==='weather')requestAnimationFrame(drawE11);
  pythonJobTabs[section]?.();
  void showDashboardExample(section);
  if(section==='plans')void openDefaultPlans();
}
tabNames.forEach((name,index)=>{
  $('tab-'+name).addEventListener('click',()=>selectTab(name));
  $('tab-'+name).addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const offset = event.key === 'ArrowLeft' ? -1 : 1;
    const next = event.key === 'Home' ? tabNames[0] : event.key === 'End' ? tabNames.at(-1)
      : tabNames[(index + offset + tabNames.length) % tabNames.length];
    selectTab(next);$('tab-'+next).focus();
  });
});
$('back-to-terrain').addEventListener('click', () => {
  selectTab('terrain');
  $('tab-terrain').focus();
});
$('terrain-beacon').addEventListener('click', () => {
  selectTab('laboratory');
  $('tab-laboratory').focus();
  if (!defaults || busy) return;
  if ($('mode').value !== 'fundacion') preset('fundacion');
  if (data?.mode !== 'fundacion') void calculate();
  else refreshPendingChanges();
});
if ($('tab-terrain').getAttribute('aria-selected') === 'true') void showTerrain();
form.addEventListener('input',()=>{updateFields();refreshPendingChanges();});
form.addEventListener('change',()=>{updateFields();refreshPendingChanges();});
$('mode').addEventListener('change',()=>{preset($('mode').value);refreshPendingChanges();});
$('construction_mode').addEventListener('change',()=>{if($('construction_mode').value==='staged'){$('profile').value='uniforme';$('source_type').value='cosine';}updateFields();refreshPendingChanges();});
$('reset').addEventListener('click',()=>{preset($('mode').value);refreshPendingChanges();});
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
window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{draw();drawE11();},80);});

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

(() => {
  const sequence = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    'ArrowLeft', 'ArrowRight', 'b', 'a', 'Enter'];
  const moves = {ArrowUp:[0,-1], ArrowDown:[0,1], ArrowLeft:[-1,0], ArrowRight:[1,0]};
  const maze = [
    '#############################',
    '#o............#............o#',
    '#..###..####..#..####..###..#',
    '#.............#.............#',
    '#.####.####.......####.####.#',
    '#......#.............#......#',
    '####.#.#...###=###...#.#.####',
    '####.#.....#     #.....#.####',
    '.....#.###.#     #.###.#.....',
    '####.#.....#     #.....#.####',
    '####.#..##.#######.##..#.####',
    '#.........P.................#',
    '#.####.####.......####.####.#',
    '#.............#.............#',
    '#..###..####..#..####..###..#',
    '#o............#............o#',
    '#############################',
  ];
  const width = maze[0].length, height = maze.length, tile = 24;
  const colors = ['#ff627c','#ffa1cd','#74e3ff','#ffc074'];
  const stepMs = 150, powerSteps = Math.round(6500/stepMs);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const playerHome = [10,11];
  const ghostDoor = [14,6], ghostExit = [14,5];
  const ghostHomes = [[12,7],[16,7],[12,9],[16,9]];
  const releaseDelays = [4000,6000,8000,10000].map(ms => Math.ceil(ms/stepMs));
  const same = (a,b) => a[0] === b[0] && a[1] === b[1];
  const posKey = ([x,y]) => y * width + x;
  const distance = (a,b) => Math.abs(a[0]-b[0]) + Math.abs(a[1]-b[1]);
  let recent = [], lastKeyTime = -Infinity, transitioning = false, arcade = null, best = 0;

  function stepFrom([x,y], [dx,dy], leavingHouse = false) {
    const next = [(x+dx+width)%width, y+dy];
    const cell = maze[next[1]]?.[next[0]];
    return cell && cell !== '#' && (leavingHouse || cell !== ' ' && cell !== '=') ? next : null;
  }

  function resetActors(game) {
    game.player = game.playerFrom = playerHome;
    game.direction = game.wanted = null;
    game.ghosts = ghostHomes.map((home, index) => ({home, position:home, previous:null, from:home,
      movedAt:0, releaseAt:releaseDelays[index], outside:false, index}));
    game.ticks = game.power = 0;
  }

  function newGame() {
    const pellets = new Map();
    maze.forEach((line,y) => Array.from(line).forEach((cell,x) => {
      if (cell === '.' || cell === 'o') pellets.set(posKey([x,y]), cell);
    }));
    const game = {pellets, score:0, lives:3, phase:'ready'};
    resetActors(game);
    return game;
  }

  function collide(game) {
    const contact = game.ghosts.filter(ghost => ghost.outside && same(ghost.position, game.player));
    if (!contact.length) return false;
    if (game.power) {
      for (const ghost of contact) {
        ghost.releaseAt = game.ticks + releaseDelays[0];
        ghost.outside = false;
        ghost.position = ghost.from = ghost.home;
        ghost.previous = null;
        game.score += 200;
      }
      return false;
    }
    game.lives--;
    game.phase = game.lives ? 'ready' : 'lost';
    if (game.lives) resetActors(game);
    return true;
  }

  function moveGhost(ghost, game) {
    if (game.ticks < ghost.releaseAt || (game.ticks-ghost.releaseAt)%2) return;
    let next;
    if (ghost.outside) {
      let choices = Object.values(moves).map(move => stepFrom(ghost.position,move)).filter(Boolean);
      const forward = ghost.previous && choices.filter(pos => !same(pos,ghost.previous));
      if (forward?.length) choices = forward;
      choices.sort((a,b) => (distance(a,game.player)-distance(b,game.player)) * (game.power ? -1 : 1));
      next = choices[0];
    } else {
      const dx = Math.sign(ghostDoor[0]-ghost.position[0]);
      next = stepFrom(ghost.position,dx ? [dx,0] : [0,-1],true);
    }
    if (!next) return;
    ghost.previous = ghost.from = ghost.position;
    ghost.position = next;
    ghost.movedAt = game.ticks;
    ghost.outside ||= same(next,ghostExit);
  }

  function tick(game) {
    if (game.phase !== 'playing') return;
    game.ticks++;
    if (game.power) game.power--;
    if (game.wanted && stepFrom(game.player,game.wanted)) game.direction = game.wanted;
    const next = game.direction && stepFrom(game.player,game.direction);
    game.playerFrom = game.player;
    if (next) game.player = next;
    const key = posKey(game.player), pellet = game.pellets.get(key);
    if (pellet) {
      game.pellets.delete(key);
      game.score += pellet === 'o' ? 50 : 10;
      if (pellet === 'o') game.power = powerSteps;
    }
    if (!game.pellets.size) { game.phase = 'won'; return; }
    if (collide(game)) return;
    for (const ghost of game.ghosts) moveGhost(ghost,game);
    collide(game);
  }

  function drawBoard() {
    const board = document.createElement('canvas');
    board.width = width*tile;
    board.height = height*tile;
    const ctx = board.getContext('2d');
    ctx.fillStyle = '#080515';
    ctx.fillRect(0,0,board.width,board.height);
    ctx.fillStyle = '#180b2d';
    ctx.beginPath();
    maze.forEach((line,y) => Array.from(line).forEach((cell,x) => {
      if (cell === '#') ctx.rect(x*tile,y*tile,tile,tile);
    }));
    ctx.fill();
    const edge = (x1,y1,x2,y2) => {ctx.moveTo(x1*tile,y1*tile);ctx.lineTo(x2*tile,y2*tile);};
    ctx.beginPath();
    maze.forEach((line,y) => Array.from(line).forEach((cell,x) => {
      if (cell !== '#') return;
      if (maze[y-1]?.[x] && maze[y-1][x] !== '#') edge(x,y,x+1,y);
      if (maze[y+1]?.[x] && maze[y+1][x] !== '#') edge(x,y+1,x+1,y+1);
      if (line[x-1] && line[x-1] !== '#') edge(x,y,x,y+1);
      if (line[x+1] && line[x+1] !== '#') edge(x+1,y,x+1,y+1);
    }));
    ctx.lineCap = 'round';
    ctx.lineWidth = 5;
    ctx.strokeStyle = '#7134a2';
    ctx.shadowColor = '#bb40ff';
    ctx.shadowBlur = 11;
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = '#eda6ff';
    ctx.stroke();
    ctx.beginPath();
    edge(ghostDoor[0],ghostDoor[1]+.45,ghostDoor[0]+1,ghostDoor[1]+.45);
    ctx.strokeStyle = '#9ff3ff';
    ctx.stroke();
    return board;
  }

  function interpolated(from, target, progress) {
    const delta = target[0]-from[0];
    const dx = Math.abs(delta)>1 ? -Math.sign(delta) : delta;
    const x = from[0]+dx*progress;
    return [x,from[1]+(target[1]-from[1])*progress];
  }

  function paint(canvas, board, game, progress) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const center = ([x,y]) => [(x+.5)*tile,(y+.5)*tile];
    const circle = (x,y,r) => {ctx.beginPath(); ctx.arc(x,y,r,0,2*Math.PI); ctx.fill();};
    const drawActor = (from,to,fraction,draw) => {
      const pos = interpolated(from,to,fraction);
      draw(...center(pos));
      if (pos[0]<0 || pos[0]>width-1) draw(...center([pos[0]+(pos[0]<0 ? width : -width),pos[1]]));
    };
    ctx.drawImage(board,0,0);
    const powerPellets = [];
    ctx.fillStyle = '#58e9ff';
    ctx.beginPath();
    for (const [key,pellet] of game.pellets) {
      const [x,y] = center([key%width,Math.floor(key/width)]);
      if (pellet === 'o') powerPellets.push([x,y]);
      else {ctx.moveTo(x+2.4,y); ctx.arc(x,y,2.4,0,2*Math.PI);}
    }
    ctx.fill();
    ctx.fillStyle = '#fff3ff';
    ctx.shadowBlur = 14;
    ctx.shadowColor = '#ba6aff';
    for (const [x,y] of powerPellets) circle(x,y,6);
    ctx.shadowBlur = 0;
    for (const ghost of game.ghosts) {
      const fraction = Math.min(1,(game.ticks-ghost.movedAt+progress)/2);
      drawActor(ghost.from,ghost.position,fraction,(x,y) => {
        ctx.fillStyle = game.power && ghost.outside ? '#526eef' : colors[ghost.index];
        ctx.beginPath();
        ctx.arc(x,y-1,9,Math.PI,0);
        ctx.lineTo(x+9,y+8); ctx.lineTo(x+5,y+5); ctx.lineTo(x+1,y+8);
        ctx.lineTo(x-3,y+5); ctx.lineTo(x-9,y+8); ctx.closePath(); ctx.fill();
        ctx.fillStyle = '#fff';
        circle(x-3,y-1,2.5); circle(x+3,y-1,2.5);
        ctx.fillStyle = '#181c44';
        circle(x-2.5,y-1,1.2); circle(x+3.5,y-1,1.2);
      });
    }
    const [dx,dy] = game.direction || [1,0];
    const angle = Math.atan2(dy,dx);
    const mouth = .3+.17*Math.cos((game.ticks+progress)*Math.PI);
    ctx.fillStyle = '#ffe45d';
    drawActor(game.playerFrom,game.player,progress,(x,y) => {
      ctx.beginPath(); ctx.moveTo(x,y);
      ctx.arc(x,y,9.5,angle+mouth,angle+2*Math.PI-mouth);
      ctx.closePath(); ctx.fill();
    });
  }

  function openArcade() {
    const previousFocus = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.className = 'visor-arcade';
    dialog.setAttribute('aria-labelledby','arcade-title');
    dialog.innerHTML = `
      <div class="arcade-cabinet">
        <header class="arcade-header">
          <h2 id="arcade-title">PAC-MAN</h2>
          <div class="arcade-actions">
            <button type="button" data-restart>Reiniciar</button>
            <button type="button" data-exit>Volver al visor</button>
          </div>
        </header>
        <div class="arcade-score">
          <span>Puntos <strong data-score>0</strong></span>
          <span>Récord <strong data-best>0</strong></span>
          <span>Vidas <strong data-lives>3</strong></span>
        </div>
        <div class="arcade-board">
          <canvas width="${width*tile}" height="${height*tile}" tabindex="0" aria-label="Laberinto de Pac-Man"></canvas>
          <p data-status role="status"></p>
        </div>
        <p class="arcade-guide">Flechas para moverte · Esc para volver al visor</p>
      </div>`;
    const get = selector => dialog.querySelector(selector);
    const canvas = get('canvas'), status = get('[data-status]');
    const board = canvas.getContext('2d') && drawBoard();
    let game = newGame(), frameId, lastFrame = null, elapsed = 0;
    const messages = {
      ready:'Usa las flechas para empezar',
      won:'¡Laberinto completo! Pulsa Enter para volver a jugar',
      lost:'Fin del juego. Pulsa Enter para volver a jugar',
    };
    function updateScore() {
      best = Math.max(best,game.score);
      get('[data-score]').textContent = game.score;
      get('[data-best]').textContent = best;
      get('[data-lives]').textContent = game.lives;
      const message = messages[game.phase] || '';
      if (status.textContent !== message) status.textContent = message;
      status.hidden = !message;
    }
    function restart() {
      game = newGame(); elapsed = 0; updateScore(); canvas.focus();
      if (board) paint(canvas,board,game,1);
    }
    get('[data-restart]').addEventListener('click',restart);
    get('[data-exit]').addEventListener('click',() => dialog.close());
    dialog.addEventListener('keydown',event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        dialog.close();
        return;
      }
      const move = Object.hasOwn(moves,event.key) && moves[event.key];
      if (event.key === 'Enter' && (game.phase === 'won' || game.phase === 'lost') && event.target === canvas) {
        event.preventDefault(); restart();
      } else if (move) {
        event.preventDefault(); event.stopPropagation();
        if (game.phase === 'ready' && stepFrom(game.player,move)) {
          game.phase = 'playing'; elapsed = stepMs; canvas.focus();
        }
        game.wanted = move;
      }
    });
    function animate(now) {
      if (!document.hidden && game.phase === 'playing') {
        elapsed += Math.min(now-(lastFrame??now),stepMs);
        if (elapsed >= stepMs) {
          elapsed -= stepMs;
          tick(game);
          updateScore();
        }
        if (board) paint(canvas,board,game,game.phase === 'playing' ? elapsed/stepMs : 1);
      }
      lastFrame = now;
      frameId = requestAnimationFrame(animate);
    }
    dialog.addEventListener('close',() => {
      cancelAnimationFrame(frameId);
      dialog.remove();
      arcade = null;
      if (previousFocus?.isConnected) previousFocus.focus({preventScroll:true});
    },{once:true});
    document.body.append(dialog);
    arcade = dialog;
    dialog.showModal();
    updateScore();
    if (board) paint(canvas,board,game,1);
    canvas.focus();
    frameId = requestAnimationFrame(animate);
  }

  document.addEventListener('keydown',event => {
    if (transitioning || arcade || event.repeat) return;
    if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey ||
        event.target?.isContentEditable || event.target?.closest?.('input, textarea, select, [role="textbox"]')) {
      recent = [];
      return;
    }
    const now = performance.now();
    if (now-lastKeyTime > 3500) recent = [];
    lastKeyTime = now;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    recent = [...recent,key].slice(-sequence.length);
    if (recent.length !== sequence.length || !recent.every((pressed,index) => pressed === sequence[index])) return;
    event.preventDefault();
    event.stopPropagation();
    recent = [];
    transitioning = true;
    document.documentElement.classList.add('visor-transition');
    setTimeout(() => {
      document.documentElement.classList.remove('visor-transition');
      transitioning = false;
      openArcade();
    },reducedMotion.matches ? 230 : 540);
  },true);
  window.addEventListener('blur',() => { recent = []; });
})();
