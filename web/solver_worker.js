'use strict';
/* Núcleo portátil: balances del solver Python adaptados a Float64Array.
 * Material homogéneo; fuente constante o pulso coseno temporal sintético.
 * G05: flujo entrante; caras a media celda; Euler explícito; último paso acortado.
 * La geometría IFC se exporta en la construcción del HTML, no se inventa aquí.
 */
function runOffline(input, pack) {
  const defaults=pack.meta.defaults, o={...defaults,...input};
  if(!input||typeof input!=='object'||Object.keys(input).some(k=>!(k in defaults)))throw Error('Parámetros desconocidos');
  if(!['fundacion','1d','2d','3d'].includes(o.mode)||!['uniforme','seno'].includes(o.profile))throw Error('Caso o perfil desconocido');
  if(!['constant','cosine'].includes(o.source_type))throw Error('Fuente desconocida');
  if(!['ifc','scaled'].includes(o.foundation_geometry))throw Error('Geometría de fundación desconocida');
  if(!Number.isInteger(o.pour_count)||o.pour_count<1||o.pour_count>12)throw Error('Cantidad de vertidas: entero entre 1 y 12');
  if(!['simultaneous','staged'].includes(o.construction_mode))throw Error('Modo constructivo desconocido');
  const envChoices={environment_mode:['standard','e10'],environment_wind:['fixed','synthetic'],
    environment_solar:['off','synthetic'],environment_formwork:['none','permanent','scheduled'],
    environment_insulation:['none','blanket'],environment_soil:['standard','equivalent']};
  if(Object.entries(envChoices).some(([key,choices])=>!choices.includes(o[key])))throw Error('Opción ambiental E10 desconocida');
  const useEnvironment=o.environment_mode==='e10';
  if(useEnvironment&&o.mode!=='fundacion')throw Error('El entorno E10 solo está disponible para la fundación');
  const staged=o.mode==='fundacion'&&o.construction_mode==='staged';
  let schedule;
  try {
    schedule=o.pour_schedule?JSON.parse(o.pour_schedule):Array.from({length:o.pour_count},(_,i)=>({start_days:i,placement_c:o.initial_c}));
    if(!Array.isArray(schedule)||schedule.length!==o.pour_count)throw Error();
    let previous=0;
    for(const r of schedule){if(!r||Object.keys(r).sort().join(',')!=='placement_c,start_days'||typeof r.start_days!=='number'||typeof r.placement_c!=='number'||!Number.isFinite(r.start_days)||!Number.isFinite(r.placement_c)||r.start_days<previous||r.start_days>30||r.placement_c< -50||r.placement_c>150)throw Error();previous=r.start_days;}
  } catch {throw Error('Cronograma inválido: revisar inicios y temperaturas por vertida');}
  for(const name of ['boundary_type','bottom_type'])if(!['dirichlet','neumann','robin'].includes(o[name]))throw Error('Condición de borde desconocida');
  for(const [name,[low,high]] of Object.entries(pack.bounds))if(typeof o[name]!=='number'||!Number.isFinite(o[name])||o[name]<low||o[name]>high)throw Error(`${name}: valor entre ${low} y ${high}`);
  if(!Number.isInteger(o.nodes)||o.nodes<8||o.nodes>(o.mode==='1d'?401:48))throw Error('Cantidad de nodos/celdas no admitida');
  if(o.dt_s!==null&&(typeof o.dt_s!=='number'||!Number.isFinite(o.dt_s)||o.dt_s<=0))throw Error('Δt debe ser positivo o automático');
  const dim=o.mode==='1d'?1:o.mode==='2d'?2:3, nodal=dim===1;
  let shape,origin=[0,0,0],lengths,delta,indices,source=null;
  if(o.mode==='fundacion') {
    const g=pack.grids[String(o.resolution_m)];if(!g)throw Error('Resolución no incluida en este HTML; elige 0.50, 0.25 o 0.20 m');
    shape=g.shape;origin=g.origin_m;lengths=g.lengths_m;delta=g.spacing_m;indices=g.active_indices;source={...pack.meta.ifc,offline_snapshot:true};
    if(o.pour_count>shape[2])throw Error('Hay vertidas sin celdas: use una malla más fina o reduzca la cantidad de vertidas');
    const reference=Array.from(lengths);
    if(o.foundation_geometry==='scaled'){lengths=[o.foundation_x_m,o.foundation_y_m,o.foundation_height_m];delta=lengths.map((v,a)=>v/shape[a]);}
    source.geometry_transform={type:o.foundation_geometry,scale_xyz:lengths.map((v,a)=>v/reference[a]),reference_lengths_m:reference};
  } else if(nodal) {
    lengths=[pack.meta.ifc.lengths_m[2],0,0];shape=[o.nodes];delta=[lengths[0]/(o.nodes-1),0,0];indices=Array.from({length:o.nodes},(_,i)=>i);source={...pack.meta.ifc,offline_snapshot:true};
  } else {
    shape=Array(dim).fill(o.nodes);lengths=[o.length_x_m,o.length_y_m,dim===3?o.length_z_m:0];delta=lengths.map((v,a)=>a<dim?v/o.nodes:0);
    indices=Array.from({length:o.nodes**dim},(_,i)=>i);
  }
  const [nx,ny=1,nz=1]=shape, total=nx*ny*nz, active=new Uint8Array(total), count=indices.length;
  const pourIndex=id=>Math.floor((id%nz+0.5)*o.pour_count/nz);
  const starts=new Float64Array(total),placement=new Float64Array(total);
  for(const i of indices){const row=schedule[pourIndex(i)]||schedule[0];starts[i]=row.start_days*86400;placement[i]=row.placement_c;active[i]=staged?(starts[i]<=0?1:0):1;}
  const positions=new Array(count), probeCell=shape.reduce((a,n)=>a*n+Math.floor(n/2),0);
  let probe=indices.indexOf(probeCell), nearest=Infinity;
  const needsProbe=probe<0;
  const k=o.conductivity_w_mk,rhocp=o.density_kg_m3*o.specific_heat_j_kgk,alpha=k/rhocp;
  const volume=nodal?delta[0]:delta[0]*delta[1]*(dim===3?delta[2]:1), capacity=rhocp*volume;
  const C=new Float64Array(total), T=new Float64Array(total), next=new Float64Array(total), power=new Float64Array(total);
  const te=new Float64Array(total), factors=new Float64Array(total);
  function factorAt(t){if(t<= -273.15||!Number.isFinite(t))throw Error('Temperatura inválida para Arrhenius');const f=Math.exp(-o.activation_energy_j_mol/8.31446261815324*(1/(t+273.15)-1/293.15));if(!Number.isFinite(f)||f<=0)throw Error('Factor Arrhenius fuera de rango');return f;}
  const diagonal=new Float64Array(total), bg=new Float64Array(total), fixed=new Float64Array(total), flux=new Float64Array(total);
  const makeBoundary=(type,t,h,q,resistance=0)=>({type,t,h:h===0?0:1/(1/h+resistance),q});
  const main=makeBoundary(o.boundary_type,o.boundary_c,o.h_w_m2k,o.flux_in_w_m2,o.resistance_m2k_w);
  const env=pack.meta.environment;
  const useSoil=useEnvironment&&o.environment_soil==='equivalent';
  const bottom=useSoil?makeBoundary('robin',env.soil.deep_temperature_c,env.soil.conductivity_w_mk/env.soil.depth_m,0)
    :makeBoundary(o.bottom_type,o.bottom_c,o.bottom_h_w_m2k,o.bottom_flux_in_w_m2);
  const environmentalFaces=[];
  const layerR=layer=>layer.thickness_m/layer.conductivity_w_mk;
  const stripTime=o.environment_strip_h*3600;
  const climate=(name,time,shift=0)=>{
    const hour=(time/3600+shift)%24, i=Math.floor(hour), f=hour-i, samples=env.weather[name];
    return (1-f)*samples[i]+f*samples[i+1];
  };
  const film=wind=>o.environment_wind==='fixed'?o.environment_h:env.convection.h_a_w_m2k+
    env.convection.h_b_w_m2k_per_m_s*wind*(env.convection.wind_height_m/10)**env.convection.wind_exponent;
  const maxFilm=useEnvironment?film(Math.max(...env.weather.wind_10m_m_s)):0;
  const pairA=new Int32Array(count*dim),pairB=new Int32Array(count*dim),pairG=new Float64Array(count*dim);let pairs=0;
  const strides=[ny*nz,nz,1], counts=[nx,ny,nz];
  const coordinates=id=>[Math.floor(id/(ny*nz)),Math.floor(id/nz)%ny,id%nz];
  for(let q=0;q<count;q++) {
    const id=indices[q], at=coordinates(id);let wave=1;
    const p=[0,0,0];
    for(let axis=0;axis<dim;axis++){p[axis]=origin[axis]+(nodal?at[axis]:at[axis]+0.5)*delta[axis];wave*=Math.sin(Math.PI*(p[axis]-origin[axis])/lengths[axis]);}
    positions[q]=p;
    if(needsProbe){const distance=p.reduce((sum,v,a)=>sum+(v-origin[a]-lengths[a]/2)**2,0);if(distance<nearest){nearest=distance;probe=q;}}
    C[id]=capacity*(nodal&&(id===0||id===nx-1)?0.5:1);
    T[id]=staged?(active[id]?placement[id]:0):o.initial_c+(o.profile==='seno'?o.amplitude_c*wave:0);
  }
  function assemble() {
    pairs=0;diagonal.fill(0);bg.fill(0);fixed.fill(0);flux.fill(0);
    environmentalFaces.length=0;
    for(const id of indices){if(!active[id])continue;const at=coordinates(id);
    for(let axis=0;axis<dim;axis++)if(at[axis]+1<counts[axis]&&active[id+strides[axis]]){
      const other=id+strides[axis],g=k*volume/delta[axis]**2;
      pairA[pairs]=id;pairB[pairs]=other;pairG[pairs++]=g;diagonal[id]+=g;diagonal[other]+=g;
    }}
  // Las caras se ensamblan una vez. Interfaces activas/inactivas: Robin/Dirichlet/Neumann declarado para expuestas.
  for(const id of indices) {
    if(!active[id])continue;
    const at=coordinates(id);
    for(let axis=0;axis<dim;axis++)for(const sign of [-1,1]) {
      const outer=at[axis]+sign<0||at[axis]+sign>=counts[axis];
      const exposed=!outer&&!active[id+sign*strides[axis]];
      if(!outer&&!(exposed&&o.mode==='fundacion'))continue;
      const base=outer&&sign<0&&axis===dim-1;
      const b=base?bottom:main,area=nodal?1:volume/delta[axis];
      if(useEnvironment&&!base){
        const side=axis!==2, top=axis===2&&sign>0;
        const form=side&&o.environment_formwork!=='none'?layerR(env.formwork):0;
        const insulation=top&&o.environment_insulation==='blanket'?layerR(env.insulation):0;
        const half=delta[axis]/(2*k);
        const removable=side&&o.environment_formwork==='scheduled';
        const solarFactor=side?env.solar.side_factor*(form?env.solar.absorptance_formwork:env.solar.absorptance_concrete):
          top?env.solar.top_factor*env.solar.absorptance_concrete:0;
        diagonal[id]+=area/(half+insulation+(removable?0:form)+1/maxFilm);
        environmentalFaces.push({id,area,half,insulation,form,removable,solarFactor});
        continue;
      }
      if(nodal&&b.type==='dirichlet')continue;
      if(b.type==='neumann')flux[id]+=b.q*area;
      else {
        const g=nodal?b.h:b.type==='dirichlet'?2*k*area/delta[axis]:b.h===0?0:area/(1/b.h+delta[axis]/(2*k));
        bg[id]+=g;fixed[id]+=g*b.t;diagonal[id]+=g;
      }
    }
  }
  }
  assemble();
  if(nodal){if(bottom.type==='dirichlet')T[0]=bottom.t;if(main.type==='dirichlet')T[nx-1]=main.t;}
  const general=0.5/(alpha*delta.slice(0,dim).reduce((s,d)=>s+1/d**2,0));
  let local=Infinity;
  for(const id of indices){if(nodal&&((id===0&&bottom.type==='dirichlet')||(id===nx-1&&main.type==='dirichlet')))continue;if(diagonal[id]>0)local=Math.min(local,C[id]/diagonal[id]);}
  const tau=o.source_duration_days*86400;
  const heatSource=t=>o.source_type==='constant'?o.source_w_m3:(t>=0&&t<tau?o.qmax_w_m3/2*(1-Math.cos(2*Math.PI*t/tau)):0);
  const limit=Math.min(general,local);
  // La cota general/2 cubre también las nuevas superficies temporales.
  const fullAutomatic=0.8*Math.min(general,staged?general:local);
  const requested=staged?Math.min(o.dt_s??Math.min(fullAutomatic,o.source_type==='cosine'?tau/100:Infinity),0.4*general,o.source_type==='cosine'?tau/100:Infinity):o.dt_s??Math.min(0.8*limit,o.source_type==='cosine'?tau/100:Infinity);
  if(requested>general)throw Error(`Estabilidad general: Δt=${requested} s; límite=${general} s`);
  if(!staged&&requested>local)throw Error(`Estabilidad local: Δt=${requested} s; límite=${local} s`);
  const dt=useEnvironment?Math.min(requested,env.max_step_s):requested;
  const duration=o.duration_days*86400,steps=Math.ceil(duration/dt)+(staged?o.pour_count:0);
  if(steps>pack.meta.max_steps)throw Error(`El caso requiere ${steps} pasos; reduce duración o usa una malla menos fina (máximo ${pack.meta.max_steps}).`);
  const every=Math.max(1,Math.ceil(steps/24)),frames=[],times=[],history={center_c:[],min_c:[],max_c:[],mean_c:[],energy:[]};
  let time=0,boundaryHeat=0,sourceHeat=0,placementEnergy=0,initialEnergy=0,maxBalance=0;
  const construction={placement_energy_j:[],source_heat_in_j:[],boundary_heat_in_j:[],equivalent_age_s:[]};
  const layerSource=Array.from({length:o.pour_count},()=>[]);
  function save(t) {
    const row=new Array(count);let sum=0,weight=0,minimum=Infinity,maximum=-Infinity,energy=0,sumCorrection=0,energyCorrection=0;
    // Suma compensada: el error de agregar miles de capacidades no debe aparentar pérdida de energía.
    for(let q=0;q<count;q++){
      const id=indices[q],v=T[id];if(!active[id]){row[q]=null;continue;}row[q]=Math.round(v*1e5)/1e5;minimum=Math.min(minimum,v);maximum=Math.max(maximum,v);
      const w=nodal&&(id===0||id===nx-1)?0.5:1, term=w*v-sumCorrection, updated=sum+term;
      sumCorrection=(updated-sum)-term;sum=updated;weight+=w;
      const e=C[id]*v-energyCorrection,newEnergy=energy+e;energyCorrection=(newEnergy-energy)-e;energy=newEnergy;
    }
    if(!frames.length)initialEnergy=energy;
    maxBalance=Math.max(maxBalance,Math.abs(energy-initialEnergy-boundaryHeat-sourceHeat-placementEnergy)/Math.max(1,Math.abs(energy),Math.abs(initialEnergy)));
    frames.push(row);times.push(t);history.center_c.push(active[indices[probe]]?T[indices[probe]]:null);history.min_c.push(weight?minimum:null);history.max_c.push(weight?maximum:null);history.mean_c.push(weight?sum/weight:null);history.energy.push(energy);
    construction.placement_energy_j.push(placementEnergy);construction.source_heat_in_j.push(sourceHeat);construction.boundary_heat_in_j.push(boundaryHeat);
    if(staged){construction.equivalent_age_s.push(indices.map(id=>te[id]));
      const sums=Array(o.pour_count).fill(0),counts=Array(o.pour_count).fill(0);
      for(const id of indices){const i=pourIndex(id);counts[i]++;if(active[id])sums[i]+=heatSource(te[id])*factorAt(T[id]);}
      sums.forEach((v,i)=>layerSource[i].push(v/counts[i]));}
  }
  save(0);
  let stepCount=0;
  for(let step=0;time<duration;step++) {
    if(step>=pack.meta.max_steps)throw Error('Demasiados pasos para el visor');
    const future=staged?schedule.map(r=>r.start_days*86400).filter(t=>t>time):[];
    let maxFactor=1;
    if(staged)for(const id of indices)if(active[id]){factors[id]=factorAt(T[id]);maxFactor=Math.max(maxFactor,factors[id]);}
    const ageCap=staged&&o.source_type==='cosine'?tau/(100*maxFactor):Infinity;
    const end=Math.min(staged?time+dt:(step+1)*dt,time+ageCap,duration,...future),width=end-time;let boundaryPower=0,sourcePower=0,bcCorrection=0,sourceCorrection=0;
    if(end<=time)throw Error('Paso menor que la precisión del reloj');
    const qNow=heatSource(time); // Inicio del paso t_n, también para el último paso acortado.
    if(useEnvironment){
      const air=climate('air_c',time), h=film(climate('wind_10m_m_s',time));
      const solar=o.environment_solar==='synthetic'?climate('shortwave_w_m2',time,0.5):0;
      for(const face of environmentalFaces){
        const {id,area,half,insulation,form,removable,solarFactor}=face;
        const layers=insulation+(removable&&time>=stripTime?0:form);
        const q=area*(air+solarFactor*solar/h-T[id])/(half+layers+1/h);
        power[id]+=q;
      }
    }
    for(const id of indices){
      if(!active[id])continue;
      const b=(useEnvironment?power[id]:0)+fixed[id]+flux[id]-bg[id]*T[id],s=(staged?heatSource(te[id])*factors[id]:qNow)*C[id]/rhocp;power[id]=b+s;
      const db=b-bcCorrection,newB=boundaryPower+db;bcCorrection=(newB-boundaryPower)-db;boundaryPower=newB;
      const ds=s-sourceCorrection,newS=sourcePower+ds;sourceCorrection=(newS-sourcePower)-ds;sourcePower=newS;
    }
    for(let j=0;j<pairs;j++){const a=pairA[j],b=pairB[j],q=pairG[j]*(T[b]-T[a]);power[a]+=q;power[b]-=q;}
    for(const id of indices)if(active[id])next[id]=T[id]+width/C[id]*power[id];
    if(nodal){if(bottom.type==='dirichlet')next[0]=bottom.t;if(main.type==='dirichlet')next[nx-1]=main.t;}
    for(const id of indices)if(active[id]){T[id]=next[id];if(staged)te[id]+=width*factors[id];}
    boundaryHeat+=boundaryPower*width;sourceHeat+=sourcePower*width;time=end;
    let changed=false;
    if(staged)for(const id of indices)if(!active[id]&&starts[id]<=time){active[id]=1;te[id]=0;T[id]=placement[id];placementEnergy+=C[id]*T[id];changed=true;}
    if(changed)assemble();
    if(useEnvironment)power.fill(0);
    stepCount=step+1;
    if(changed||(step+1)%every===0||time===duration)save(time);
  }
  function describe(b){return b.type==='dirichlet'?`Dirichlet · ${b.t} °C`:b.type==='neumann'?(b.q===0?'Adiabático · flujo 0 W/m²':`Neumann · entran ${b.q} W/m²`):`Robin · aire ${b.t} °C · h efectivo ${Number(b.h.toPrecision(6))} W/(m²·K)`;}
  const curveTimes=new Set([...Array.from({length:201},(_,i)=>i*duration/200),...times]);
  if(o.source_type==='cosine')for(const t of [tau/2,tau])if(t<=duration)curveTimes.add(t);
  if(staged)for(const r of schedule)for(const offset of [0,tau/2,tau]){const t=r.start_days*86400+offset;if(t<=duration)curveTimes.add(t);}
  const sourceTimes=Array.from(curveTimes).sort((a,b)=>a-b);
  let pourPlan=null;
  if(o.mode==='fundacion'){
    const ids=indices.map(id=>1+Math.floor((id%nz+0.5)*o.pour_count/nz));
    const layers=Array.from({length:o.pour_count},(_,i)=>({id:i+1,z_min_m:origin[2]+lengths[2]*i/o.pour_count,z_max_m:origin[2]+lengths[2]*(i+1)/o.pour_count,cells:0,voxel_volume_m3:0}));
    for(const id of ids)layers[id-1].cells++;
    for(const row of layers){if(!row.cells)throw Error('Hay vertidas sin celdas: use una malla más fina o reduzca la cantidad de vertidas');row.voxel_volume_m3=row.cells*volume;}
    if(staged)layers.forEach((r,i)=>Object.assign(r,{start_s:schedule[i].start_days*86400,placement_c:schedule[i].placement_c}));
    pourPlan={type:staged?'Construcción por etapas · edad local':'Capas horizontales de igual altura; sin cronograma de colocación',simultaneous:!staged,cell_pour_id:Array.from(ids),layers};
  }
  return {mode:o.mode,parameters:o,ifc:source,shape,dimension:dim,origin_m:origin,lengths_m:lengths,spacing_m:delta,
    positions_m:positions,active_indices:Array.from(indices),frames_c:frames,time_s:times,temperature_precision_decimals:5,
    history,probe_position_m:positions[probe],boundary_used:{
      laterales_y_expuestas:useEnvironment?'Robin ambiental E10 · aire sintético y opciones por orientación':describe(main),
      base:(useSoil?'Suelo equivalente · ':'')+describe(bottom)},
    source_curve:staged&&o.activation_energy_j_mol>0?{time_s:times,rate_w_m3:times.map(()=>0),layers:layerSource.map((rate_w_m3,i)=>({id:i+1,rate_w_m3})),description:'Potencia instantánea media por vertida; Arrhenius por celda.'}:{time_s:sourceTimes,rate_w_m3:sourceTimes.map(heatSource),...(staged?{layers:schedule.map((r,i)=>({id:i+1,rate_w_m3:sourceTimes.map(t=>t<r.start_days*86400?0:heatSource(t-r.start_days*86400))}))}:{})},
    pour_plan:pourPlan,
    construction:staged?construction:null,
    stats:{cells:count,steps:stepCount,dt_s:dt,limit_dt_s:staged?general/2:limit,alpha_m2_s:alpha,balance_relative_error:nodal?null:maxBalance,energy_unit:nodal?'J/m²':'J'},
    data_status:'Ensayo sintético portátil. Geometría IFC incluida al exportar; cálculo Float64 en este navegador.',
    calculation_engine:'JavaScript Float64 · contraste automatizado con el solver Python'};
}

if(typeof self!=='undefined')self.onmessage=event=>{try{self.postMessage({id:event.data.id,result:runOffline(event.data.options,event.data.pack)});}catch(error){self.postMessage({id:event.data.id,error:error.message});}};
// Exportación únicamente para las pruebas cruzadas de desarrollo, sin dependencia en el HTML.
if(typeof module!=='undefined')module.exports={runOffline};
