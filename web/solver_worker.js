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
  for(const name of ['boundary_type','bottom_type'])if(!['dirichlet','neumann','robin'].includes(o[name]))throw Error('Condición de borde desconocida');
  for(const [name,[low,high]] of Object.entries(pack.bounds))if(typeof o[name]!=='number'||!Number.isFinite(o[name])||o[name]<low||o[name]>high)throw Error(`${name}: valor entre ${low} y ${high}`);
  if(!Number.isInteger(o.nodes)||o.nodes<8||o.nodes>(o.mode==='1d'?401:48))throw Error('Cantidad de nodos/celdas no admitida');
  if(o.dt_s!==null&&(typeof o.dt_s!=='number'||!Number.isFinite(o.dt_s)||o.dt_s<=0))throw Error('Δt debe ser positivo o automático');
  const dim=o.mode==='1d'?1:o.mode==='2d'?2:3, nodal=dim===1;
  let shape,origin=[0,0,0],lengths,delta,indices,source=null;
  if(o.mode==='fundacion') {
    const g=pack.grids[String(o.resolution_m)];if(!g)throw Error('Resolución no incluida en este HTML; elige 0.50, 0.25 o 0.20 m');
    shape=g.shape;origin=g.origin_m;lengths=g.lengths_m;delta=g.spacing_m;indices=g.active_indices;source={...pack.meta.ifc,offline_snapshot:true};
  } else if(nodal) {
    lengths=[pack.meta.ifc.lengths_m[2],0,0];shape=[o.nodes];delta=[lengths[0]/(o.nodes-1),0,0];indices=Array.from({length:o.nodes},(_,i)=>i);source={...pack.meta.ifc,offline_snapshot:true};
  } else {
    shape=Array(dim).fill(o.nodes);lengths=[o.length_x_m,o.length_y_m,dim===3?o.length_z_m:0];delta=lengths.map((v,a)=>a<dim?v/o.nodes:0);
    indices=Array.from({length:o.nodes**dim},(_,i)=>i);
  }
  const [nx,ny=1,nz=1]=shape, total=nx*ny*nz, active=new Uint8Array(total), count=indices.length;
  for(const i of indices)active[i]=1;
  const positions=new Array(count), probeCell=shape.reduce((a,n)=>a*n+Math.floor(n/2),0);
  let probe=indices.indexOf(probeCell), nearest=Infinity;
  const needsProbe=probe<0;
  const k=o.conductivity_w_mk,rhocp=o.density_kg_m3*o.specific_heat_j_kgk,alpha=k/rhocp;
  const volume=nodal?delta[0]:delta[0]*delta[1]*(dim===3?delta[2]:1), capacity=rhocp*volume;
  const C=new Float64Array(total), T=new Float64Array(total), next=new Float64Array(total), power=new Float64Array(total);
  const diagonal=new Float64Array(total), bg=new Float64Array(total), fixed=new Float64Array(total), flux=new Float64Array(total);
  const makeBoundary=(type,t,h,q,resistance=0)=>({type,t,h:h===0?0:1/(1/h+resistance),q});
  const main=makeBoundary(o.boundary_type,o.boundary_c,o.h_w_m2k,o.flux_in_w_m2,o.resistance_m2k_w);
  const bottom=makeBoundary(o.bottom_type,o.bottom_c,o.bottom_h_w_m2k,o.bottom_flux_in_w_m2);
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
    T[id]=o.initial_c+(o.profile==='seno'?o.amplitude_c*wave:0);
    for(let axis=0;axis<dim;axis++)if(at[axis]+1<counts[axis]&&active[id+strides[axis]]){
      const other=id+strides[axis],g=k*volume/delta[axis]**2;
      pairA[pairs]=id;pairB[pairs]=other;pairG[pairs++]=g;diagonal[id]+=g;diagonal[other]+=g;
    }
  }
  // Las caras se ensamblan una vez. Interfaces activas/inactivas: Robin/Dirichlet/Neumann declarado para expuestas.
  for(const id of indices) {
    const at=coordinates(id);
    for(let axis=0;axis<dim;axis++)for(const sign of [-1,1]) {
      const outer=at[axis]+sign<0||at[axis]+sign>=counts[axis];
      const exposed=!outer&&!active[id+sign*strides[axis]];
      if(!outer&&!(exposed&&o.mode==='fundacion'))continue;
      const base=outer&&sign<0&&axis===dim-1;
      const b=base?bottom:main,area=nodal?1:volume/delta[axis];
      if(nodal&&b.type==='dirichlet')continue;
      if(b.type==='neumann')flux[id]+=b.q*area;
      else {
        const g=nodal?b.h:b.type==='dirichlet'?2*k*area/delta[axis]:b.h===0?0:area/(1/b.h+delta[axis]/(2*k));
        bg[id]+=g;fixed[id]+=g*b.t;diagonal[id]+=g;
      }
    }
  }
  if(nodal){if(bottom.type==='dirichlet')T[0]=bottom.t;if(main.type==='dirichlet')T[nx-1]=main.t;}
  const general=0.5/(alpha*delta.slice(0,dim).reduce((s,d)=>s+1/d**2,0));
  let local=Infinity;
  for(const id of indices){if(nodal&&((id===0&&bottom.type==='dirichlet')||(id===nx-1&&main.type==='dirichlet')))continue;if(diagonal[id]>0)local=Math.min(local,C[id]/diagonal[id]);}
  const tau=o.source_duration_days*86400;
  const heatSource=t=>o.source_type==='constant'?o.source_w_m3:(t>=0&&t<tau?o.qmax_w_m3/2*(1-Math.cos(2*Math.PI*t/tau)):0);
  const limit=Math.min(general,local),dt=o.dt_s??Math.min(0.8*limit,o.source_type==='cosine'?tau/100:Infinity);
  if(dt>general)throw Error(`Estabilidad general: Δt=${dt} s; límite=${general} s`);
  if(dt>local)throw Error(`Estabilidad local: Δt=${dt} s; límite=${local} s`);
  const duration=o.duration_days*86400,steps=Math.ceil(duration/dt);
  if(steps>pack.meta.max_steps)throw Error(`El caso requiere ${steps} pasos; reduce duración o usa una malla menos fina (máximo ${pack.meta.max_steps}).`);
  const every=Math.max(1,Math.ceil(steps/24)),frames=[],times=[],history={center_c:[],min_c:[],max_c:[],mean_c:[],energy:[]};
  let time=0,boundaryHeat=0,sourceHeat=0,initialEnergy=0,maxBalance=0;
  function save(t) {
    const row=new Array(count);let sum=0,weight=0,minimum=Infinity,maximum=-Infinity,energy=0,sumCorrection=0,energyCorrection=0;
    // Suma compensada: el error de agregar miles de capacidades no debe aparentar pérdida de energía.
    for(let q=0;q<count;q++){
      const id=indices[q],v=T[id];row[q]=Math.round(v*1e5)/1e5;minimum=Math.min(minimum,v);maximum=Math.max(maximum,v);
      const w=nodal&&(id===0||id===nx-1)?0.5:1, term=w*v-sumCorrection, updated=sum+term;
      sumCorrection=(updated-sum)-term;sum=updated;weight+=w;
      const e=C[id]*v-energyCorrection,newEnergy=energy+e;energyCorrection=(newEnergy-energy)-e;energy=newEnergy;
    }
    if(!frames.length)initialEnergy=energy;
    maxBalance=Math.max(maxBalance,Math.abs(energy-initialEnergy-boundaryHeat-sourceHeat)/Math.max(1,Math.abs(initialEnergy)));
    frames.push(row);times.push(t);history.center_c.push(T[indices[probe]]);history.min_c.push(minimum);history.max_c.push(maximum);history.mean_c.push(sum/weight);history.energy.push(energy);
  }
  save(0);
  for(let step=0;step<steps;step++) {
    const end=Math.min((step+1)*dt,duration),width=end-time;let boundaryPower=0,sourcePower=0,bcCorrection=0,sourceCorrection=0;
    const qNow=heatSource(time); // Inicio del paso t_n, también para el último paso acortado.
    for(const id of indices){
      const b=fixed[id]+flux[id]-bg[id]*T[id],s=qNow*C[id]/rhocp;power[id]=b+s;
      const db=b-bcCorrection,newB=boundaryPower+db;bcCorrection=(newB-boundaryPower)-db;boundaryPower=newB;
      const ds=s-sourceCorrection,newS=sourcePower+ds;sourceCorrection=(newS-sourcePower)-ds;sourcePower=newS;
    }
    for(let j=0;j<pairs;j++){const a=pairA[j],b=pairB[j],q=pairG[j]*(T[b]-T[a]);power[a]+=q;power[b]-=q;}
    for(const id of indices)next[id]=T[id]+width/C[id]*power[id];
    if(nodal){if(bottom.type==='dirichlet')next[0]=bottom.t;if(main.type==='dirichlet')next[nx-1]=main.t;}
    for(const id of indices)T[id]=next[id];
    boundaryHeat+=boundaryPower*width;sourceHeat+=sourcePower*width;time=end;
    if((step+1)%every===0||step+1===steps)save(time);
  }
  function describe(b){return b.type==='dirichlet'?`Dirichlet · ${b.t} °C`:b.type==='neumann'?(b.q===0?'Adiabático · flujo 0 W/m²':`Neumann · entran ${b.q} W/m²`):`Robin · aire ${b.t} °C · h efectivo ${Number(b.h.toPrecision(6))} W/(m²·K)`;}
  const curveTimes=new Set([...Array.from({length:201},(_,i)=>i*duration/200),...times]);
  if(o.source_type==='cosine')for(const t of [tau/2,tau])if(t<=duration)curveTimes.add(t);
  const sourceTimes=Array.from(curveTimes).sort((a,b)=>a-b);
  return {mode:o.mode,parameters:o,ifc:source,shape,dimension:dim,origin_m:origin,lengths_m:lengths,spacing_m:delta,
    positions_m:positions,active_indices:Array.from(indices),frames_c:frames,time_s:times,temperature_precision_decimals:5,
    history,probe_position_m:positions[probe],boundary_used:{laterales_y_expuestas:describe(main),base:describe(bottom)},
    source_curve:{time_s:sourceTimes,rate_w_m3:sourceTimes.map(heatSource)},
    stats:{cells:count,steps,dt_s:dt,limit_dt_s:limit,alpha_m2_s:alpha,balance_relative_error:nodal?null:maxBalance,energy_unit:nodal?'J/m²':'J'},
    data_status:'Ensayo sintético portátil. Geometría IFC incluida al exportar; cálculo Float64 en este navegador.',
    calculation_engine:'JavaScript Float64 · contraste automatizado con el solver Python'};
}

if(typeof self!=='undefined')self.onmessage=event=>{try{self.postMessage({id:event.data.id,result:runOffline(event.data.options,event.data.pack)});}catch(error){self.postMessage({id:event.data.id,error:error.message});}};
// Exportación únicamente para las pruebas cruzadas de desarrollo, sin dependencia en el HTML.
if(typeof module!=='undefined')module.exports={runOffline};
