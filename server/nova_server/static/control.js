// Token stays only in browser memory, never localStorage/cookies.
let token = null;
let connectDrafts = {};
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
 const entries=[['NOVA Core',j.nova_core],['Jellyfin',j.jellyfin.state],['Info Jellyfin',j.jellyfin.reason||j.jellyfin.version||'—'],['Diretórios configurados',j.library_roots.map(x=>x.container_path+' (leitura e permissões por verificar)').join(' · ')],['NOVA Connect',j.connect.state],['NOVA Directory',j.directory.state]];
 for(const [k,v] of entries){const dt=document.createElement('dt');dt.textContent=k;const dd=document.createElement('dd');dd.textContent=v;d.append(dt,dd);}
 el('overview').replaceChildren(d);
 await loadConnect();
}
function showProviderFields(){
 const provider=el('provider').value;
 const saved=connectDrafts[provider]||{};
 const fields=el('providerFields');fields.replaceChildren();
 el('connectDraft').elements.gateway_url.value=saved.gateway_url||'';
 const specs={wireguard:[['gateway_mode','Gateway','select'],['endpoint_host','Endereço público/DNS do gateway WireGuard','text'],['endpoint_port','Porta UDP do gateway','number']],tailscale:[['tailnet','Tailnet do proprietário','text']],netbird:[['management_url','Serviço de gestão NetBird (HTTPS)','url']]};
 for(const [name,title,type] of specs[provider]){
  const label=document.createElement('label');label.textContent=title;
  const input=document.createElement(type==='select'?'select':'input');input.name=name;input.required=true;
  if(type==='select'){for(const [value,text] of [['managed','Gerido pelo NOVA (planeado)'],['existing','Gateway existente']]){const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option);}}
  else{input.type=type;input.maxLength=512;if(type==='number'){input.min='1';input.max='65535';input.step='1';}}
  input.value=saved[name]??(name==='gateway_mode'?'managed':name==='endpoint_port'?'51820':'');
  label.append(input);fields.append(label);
 }
}
async function loadConnect(){
 const response=await fetch('/api/v1/admin/connect',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 if(!response.ok){write(el('connectMessage'),'Não foi possível carregar os rascunhos.');return;}
 connectDrafts=(await response.json()).drafts;showProviderFields();
 write(el('connectMessage'),'Acesso remoto desativado. Três fornecedores previstos; ligações ainda por implementar e validar.');
}
el('provider').addEventListener('change',showProviderFields);
el('connectDraft').addEventListener('submit',async ev=>{
 ev.preventDefault();if(!token)return;
 const data=Object.fromEntries(new FormData(ev.currentTarget));data.schema_version=1;
 if(data.provider==='wireguard')data.endpoint_port=Number(data.endpoint_port);
 try{
  const response=await fetch('/api/v1/admin/connect/draft',{method:'PUT',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(response.status===401){token=null;el('ownerPanel').hidden=true;write(el('loginError'),'Sessão expirada.');return;}
  if(!response.ok){write(el('connectMessage'),'Configuração inválida. Usa um gateway HTTPS com IPv4 privado e verifica os campos do fornecedor.');return;}
  connectDrafts[data.provider]=data;write(el('connectMessage'),'Rascunho guardado. A ligação remota continua desativada.');
 }catch{write(el('connectMessage'),'Não foi possível guardar o rascunho.');}
});
el('login').addEventListener('submit',async ev=>{
 ev.preventDefault();const form=ev.currentTarget;write(el('loginError'),'');const fd=new FormData(form);
 try{const r=await fetch('/api/v1/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})});
 if(!r.ok){write(el('loginError'),r.status===429?'Muitas tentativas. Aguarda 15 minutos.':'Login inválido.');return;}
 const j=await r.json();token=j.access_token;form.reset();el('ownerPanel').hidden=false;await loadOverview();}
 catch{write(el('loginError'),'Não foi possível ligar ao servidor.');}
});
el('logout').addEventListener('click',async()=>{if(token){await fetch('/api/v1/admin/logout',{method:'POST',headers:{Authorization:'Bearer '+token}}).catch(()=>{});}token=null;el('ownerPanel').hidden=true;});
el('refresh').addEventListener('click',loadOverview);status();
