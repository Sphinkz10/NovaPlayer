// Token stays only in browser memory, never localStorage/cookies.
let token = null;
const el=id=>document.getElementById(id);
const write=(target,message)=>{target.textContent=message};
async function status(){
 try {const r=await fetch('/api/v1/status',{cache:'no-store'});const j=await r.json();
 write(el('publicStatus'),j.owner_setup_required?'Primeira configuração pendente: usa scripts/first_run.py.':'NOVA Core ativo · Proprietário configurado · Acesso remoto desativado.');}
 catch {write(el('publicStatus'),'Serviço temporariamente indisponível.');}
}
async function loadOverview(){
 if(!token)return;
 const r=await fetch('/api/v1/admin/overview',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 if(r.status===401){token=null;el('ownerPanel').hidden=true;write(el('loginError'),'Sessão expirada.');return;}
 if(!r.ok){write(el('overview'),'Falha ao consultar diagnóstico.');return;}
 const j=await r.json();const d=document.createElement('dl');
 const entries=[['NOVA Core',j.nova_core],['Jellyfin',j.jellyfin.state],['Info Jellyfin',j.jellyfin.reason||j.jellyfin.version||'—'],['Diretórios',j.library_roots.map(x=>x.container_path).join(' · ')],['NOVA Connect',j.connect.state],['NOVA Directory',j.directory.state]];
 for(const [k,v] of entries){const dt=document.createElement('dt');dt.textContent=k;const dd=document.createElement('dd');dd.textContent=v;d.append(dt,dd);}
 el('overview').replaceChildren(d);
}
el('login').addEventListener('submit',async ev=>{
 ev.preventDefault();write(el('loginError'),'');const fd=new FormData(ev.currentTarget);
 try{const r=await fetch('/api/v1/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})});
 if(!r.ok){write(el('loginError'),r.status===429?'Muitas tentativas. Aguarda 15 minutos.':'Login inválido.');return;}
 const j=await r.json();token=j.access_token;ev.currentTarget.reset();el('ownerPanel').hidden=false;await loadOverview();}
 catch{write(el('loginError'),'Não foi possível ligar ao servidor.');}
});
el('logout').addEventListener('click',async()=>{if(token){await fetch('/api/v1/admin/logout',{method:'POST',headers:{Authorization:'Bearer '+token}}).catch(()=>{});}token=null;el('ownerPanel').hidden=true;});
el('refresh').addEventListener('click',loadOverview);status();
