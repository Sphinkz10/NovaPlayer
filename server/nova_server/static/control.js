// Token stays only in browser memory, never localStorage/cookies.
let token = null;
let connectDrafts = {};
let libraryChoices=[];
const el=id=>document.getElementById(id);
const write=(target,message)=>{target.textContent=message};
const controlPages=new Set(['overview','libraries','people','directory','connections']);
function showControlPage(page,focus=false){
 if(!controlPages.has(page))page='overview';
 document.querySelectorAll('.control-view').forEach(view=>{view.hidden=view.id!=='view-'+page;});
 document.querySelectorAll('.sidebar nav [data-page]').forEach(link=>{
  if(link.dataset.page===page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
 });
 document.title=(el('heading-'+page)?.textContent||'NOVA')+' · NOVA Control';
 if(focus&&token){el('heading-'+page).focus();window.scrollTo({top:0,behavior:'instant'});}
}
function syncSession(){
 el('ownerPanel').hidden=!token;el('publicPanel').hidden=Boolean(token);
 if(token)showControlPage(location.hash.slice(1),true);else{document.title='Entrar · NOVA Control';el('login').elements.username.focus();}
}
document.querySelectorAll('[data-page]').forEach(link=>link.addEventListener('click',event=>{
 event.preventDefault();if(!token)return;
 const page=link.dataset.page;
 if(location.hash!=='#'+page)history.pushState(null,'','#'+page);
 showControlPage(page,true);
}));
window.addEventListener('popstate',()=>{if(token)showControlPage(location.hash.slice(1),true);});
window.addEventListener('hashchange',()=>{if(token)showControlPage(location.hash.slice(1),true);});
async function status(){
 try {const r=await fetch('/api/v1/status',{cache:'no-store'});const j=await r.json();
 el('bootstrapPanel').hidden=!j.owner_setup_required;
 write(el('publicStatus'),j.owner_setup_required?'Cria o proprietário para iniciar a configuração.':'NOVA Core ativo · Proprietário configurado.');}
 catch {write(el('publicStatus'),'Serviço temporariamente indisponível.');}
}
async function loadOverview(){
 if(!token)return;
 const r=await fetch('/api/v1/admin/overview',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 if(r.status===401){token=null;syncSession();write(el('loginError'),'Sessão expirada.');return;}
 if(!r.ok){write(el('overview'),'Falha ao consultar diagnóstico.');return;}
 const j=await r.json();const d=document.createElement('dl');
 const entries=[['NOVA Core',j.nova_core],['Jellyfin',j.jellyfin.state],['Info Jellyfin',j.jellyfin.reason||j.jellyfin.version||'—'],['Diretórios configurados',j.library_roots.map(x=>x.container_path+' (leitura e permissões por verificar)').join(' · ')],['NOVA Connect',j.connect.state],['NOVA Directory',j.directory.state]];
 for(const [k,v] of entries){const dt=document.createElement('dt');dt.textContent=k;const dd=document.createElement('dd');dd.textContent=v;d.append(dt,dd);}
 el('overview').replaceChildren(d);
 await loadConnect();
 await loadWireGuardEnrollments();
 await loadTailscale();
 await loadSetup();
 await loadDevices();
 await loadMembers();
 await loadDirectory();
 await loadLan();
}
async function loadLan(){
 const r=await fetch('/api/v1/admin/lan',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 el('lanPanel').hidden=!r.ok;
 if(r.ok){const data=await r.json();write(el('lanConnection'),'Directory: '+data.directory+' · Impressão digital TLS: '+data.fingerprint);}
}
el('lanAccountForm').addEventListener('submit',async event=>{
 event.preventDefault();if(!token)return;
 const form=event.currentTarget;const payload=Object.fromEntries(new FormData(form));
 form.elements.password.value='';form.elements.member_password.value='';
 const session=token;const button=form.querySelector('button');button.disabled=true;
 try{const r=await fetch('/api/v1/admin/directory/accounts',{method:'POST',headers:{Authorization:'Bearer '+session,'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(token!==session)return;
  write(el('lanAccountMessage'),r.ok?'Conta criada. O familiar já pode entrar e pedir a associação da TV.':'Conta não criada. Verifica a publicação, a conta proprietária e se o nome já existe.');
 }catch{if(token===session)write(el('lanAccountMessage'),'Ligação interrompida. Verifica o estado antes de repetir.');}
 finally{button.disabled=false;}
});
el('logout').addEventListener('click',()=>{el('lanPanel').hidden=true;el('lanAccountForm').reset();write(el('lanConnection'),'');write(el('lanAccountMessage'),'');});
function showSetupReport(report){
 libraryChoices=report?.libraries||[];
 showMemberLibraries();
 if(!report){write(el('setupReport'),'Ainda não existe uma verificação de instalação.');return;}
 write(el('setupReport'),'Última verificação: '+new Date(report.observed_at*1000).toLocaleString('pt-PT')+
  '. Diretórios acessíveis para listagem. '+report.libraries.map(lib=>lib.name+': '+lib.indexed_items+' itens indexados').join(' · ')+
  '. Permissões de só leitura e reprodução ainda por validar no servidor.');
}
async function loadSetup(){
 const r=await fetch('/api/v1/admin/setup',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
 if(r.ok)showSetupReport((await r.json()).last_observation);
}
el('bootstrap').addEventListener('submit',async ev=>{
 ev.preventDefault();const form=ev.currentTarget;const data=new FormData(form);
 try{
  const r=await fetch('/api/v1/admin/bootstrap',{method:'POST',headers:{'Content-Type':'application/json','X-NOVA-Bootstrap':data.get('bootstrap_code')},body:JSON.stringify({username:data.get('owner_name'),password:data.get('owner_password')})});
  if(!r.ok){write(el('bootstrapMessage'),'Não foi possível criar a conta. Verifica o código, o utilizador e a palavra-passe.');return;}
  form.reset();await status();write(el('loginError'),'Proprietário criado. Entra com a conta NOVA.');
 }catch{write(el('bootstrapMessage'),'Servidor indisponível. Tenta novamente.');}
});
async function configureJellyfin(configure){
 if(!token)return;const form=el('jellyfinSetup');
 if(!form.reportValidity())return;
 const data=new FormData(form);const payload={username:data.get('jf_username'),password:data.get('jf_password')};
 if(configure){payload.server_name=data.get('server_name');const separate=el('libraryLayout').value==='two';
  payload.libraries=[{name:data.get('library_name'),collection_type:data.get('collection_type'),roots:separate?['source-a']:['source-a','source-b']}];
  if(separate)payload.libraries.push({name:data.get('library_name_b'),collection_type:data.get('collection_type_b'),roots:['source-b']});}
 const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
 write(el('setupMessage'),'A contactar o Jellyfin…');
 try{
  const r=await fetch('/api/v1/admin/setup/jellyfin'+(configure?'':'/verify'),{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await r.json();
  if(!r.ok){const messages={setup_busy:'Já existe uma configuração em curso.',jellyfin_identity_changed:'A identidade do Jellyfin mudou. Verifica a instalação antes de continuar.',library_conflict:'Existe uma biblioteca com nome ou origens incompatíveis. Verifica as bibliotecas no Jellyfin.',jellyfin_credentials_rejected:'Credenciais Jellyfin rejeitadas. Usa a conta administrativa existente para retomar.',jellyfin_admin_required:'É necessária uma conta administrativa Jellyfin.',new_password_too_short:'Uma conta Jellyfin nova exige pelo menos 14 caracteres.',jellyfin_setup_required:'Conclui primeiro a configuração.'};
   write(el('setupMessage'),r.status===401?'Sessão NOVA expirada. Volta a entrar.':messages[result.detail]||'Não foi possível concluir. Verifica os dados e o serviço Jellyfin; podes retomar a operação.');return;}
  showSetupReport(result);write(el('setupMessage'),configure?'Jellyfin configurado. Indexação pedida; a contagem pode ainda estar a atualizar.':'Verificação atualizada.');
 }catch{write(el('setupMessage'),'Ligação interrompida. Podes retomar a operação.');}
 finally{form.elements.jf_password.value='';buttons.forEach(b=>b.disabled=false);}
}
el('jellyfinSetup').addEventListener('submit',ev=>{ev.preventDefault();configureJellyfin(true);});
el('verifyJellyfin').addEventListener('click',()=>configureJellyfin(false));
el('libraryLayout').addEventListener('change',()=>{
 const separate=el('libraryLayout').value==='two';el('libraryB').hidden=!separate;
 el('jellyfinSetup').elements.library_name_b.required=separate;
});
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
let tailscalePolicy=null;
let tailscaleBusy=false;
let tailscaleGeneration=0;
function tailscaleButtons(){
 el('tailscaleApprove').disabled=tailscaleBusy||!tailscalePolicy||tailscalePolicy.profile_approved;
 el('tailscaleDisable').disabled=tailscaleBusy||!tailscalePolicy||!tailscalePolicy.profile_approved;
 el('tailscaleRefresh').disabled=tailscaleBusy;
}
function showTailscale(data){
 const prepared=['approved','approval_required'].includes(data.state);
 tailscalePolicy=prepared?data:null;el('tailscalePolicy').replaceChildren();
 write(el('tailscaleStatus'),!prepared?'Perfil não preparado. Usa o preparador no PC antes da associação das TVs.':
  data.profile_approved?'Perfil aprovado para entrega às TVs associadas. A disponibilidade do túnel ainda tem de ser confirmada na TV.':
   'Perfil preparado. Compara os endereços e o certificado antes de aprovar.');
 if(prepared)for(const [name,value] of [['Coordenador',data.control_origin],['NOVA no Tailscale',data.client_origin],
  ['NOVA na LAN',data.base_origin],['Certificado TLS · SHA-256',data.certificate_sha256]]){
  const dt=document.createElement('dt');dt.textContent=name;const dd=document.createElement('dd');dd.textContent=value;el('tailscalePolicy').append(dt,dd);
 }
 tailscaleButtons();
}
async function loadTailscale(){
 if(!token)return;const session=token;const generation=tailscaleGeneration;
 try{const r=await fetch('/api/v1/admin/connect/tailscale',{headers:{Authorization:'Bearer '+session},cache:'no-store'});
  if(token!==session||generation!==tailscaleGeneration)return;
  if(!r.ok){tailscalePolicy=null;tailscaleButtons();write(el('tailscaleStatus'),'Não foi possível verificar o perfil preparado.');return;}
  const data=await r.json();if(token===session&&generation===tailscaleGeneration)showTailscale(data);
 }catch{if(token===session&&generation===tailscaleGeneration){tailscalePolicy=null;tailscaleButtons();write(el('tailscaleStatus'),'Perfil indisponível. Atualiza antes de aprovar.');}}
}
async function decideTailscale(approve){
 if(!token||tailscaleBusy||!tailscalePolicy)return;
 const session=token;const generation=++tailscaleGeneration;
 const payload={revision:tailscalePolicy.revision,policy_digest:tailscalePolicy.policy_digest,approve};
 tailscaleBusy=true;tailscaleButtons();
 try{const r=await fetch('/api/v1/admin/connect/tailscale',{method:'POST',headers:{Authorization:'Bearer '+session,'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(token!==session||generation!==tailscaleGeneration)return;
  const data=await r.json();if(token!==session||generation!==tailscaleGeneration)return;
  if(r.ok){showTailscale(data);write(el('tailscaleMessage'),approve?'Perfil aprovado. A TV ainda precisa de confirmar o túnel e a identidade NOVA.':'Perfil desativado. A API NOVA recusa o transporte Tailscale. A remoção do peer no tailnet é uma operação separada.');}
  else{tailscalePolicy=null;write(el('tailscaleMessage'),r.status===409?'O perfil mudou. Atualiza e verifica os dados antes de decidir.':'Decisão recusada. Verifica a sessão e o perfil preparado.');}
 }catch{if(token===session&&generation===tailscaleGeneration){tailscalePolicy=null;write(el('tailscaleMessage'),'Ligação interrompida. Atualiza o estado antes de repetir.');}}
 finally{if(generation===tailscaleGeneration){tailscaleBusy=false;tailscaleButtons();}}
}
el('tailscaleRefresh').addEventListener('click',loadTailscale);
el('tailscaleApprove').addEventListener('click',()=>decideTailscale(true));
el('tailscaleDisable').addEventListener('click',()=>decideTailscale(false));
el('logout').addEventListener('click',()=>{tailscaleGeneration++;tailscaleBusy=false;tailscalePolicy=null;el('tailscalePolicy').replaceChildren();write(el('tailscaleStatus'),'');write(el('tailscaleMessage'),'');tailscaleButtons();});
el('provider').addEventListener('change',showProviderFields);
el('connectDraft').addEventListener('submit',async ev=>{
 ev.preventDefault();if(!token)return;
 const data=Object.fromEntries(new FormData(ev.currentTarget));data.schema_version=1;
 if(data.provider==='wireguard')data.endpoint_port=Number(data.endpoint_port);
 try{
  const response=await fetch('/api/v1/admin/connect/draft',{method:'PUT',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(response.status===401){token=null;syncSession();write(el('loginError'),'Sessão expirada.');return;}
  if(!response.ok){write(el('connectMessage'),'Configuração inválida. Usa um gateway HTTPS com IPv4 privado e verifica os campos do fornecedor.');return;}
  connectDrafts[data.provider]=data;write(el('connectMessage'),'Rascunho guardado. A ligação remota continua desativada.');
 }catch{write(el('connectMessage'),'Não foi possível guardar o rascunho.');}
});
el('login').addEventListener('submit',async ev=>{
 ev.preventDefault();const form=ev.currentTarget;write(el('loginError'),'');const fd=new FormData(form);
 try{const r=await fetch('/api/v1/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})});
 if(!r.ok){write(el('loginError'),r.status===429?'Muitas tentativas. Aguarda 15 minutos.':'Login inválido.');return;}
 const j=await r.json();token=j.access_token;form.reset();syncSession();await loadOverview();}
 catch{write(el('loginError'),'Não foi possível ligar ao servidor.');}
});
el('logout').addEventListener('click',async()=>{const session=token;token=null;syncSession();el('login').elements.username.focus();if(session){await fetch('/api/v1/admin/logout',{method:'POST',headers:{Authorization:'Bearer '+session}}).catch(()=>{});}});
el('refresh').addEventListener('click',loadOverview);status();

// Explicit review before approval. Client labels are untrusted text, never HTML.
let deviceReview = null;
let deviceReviewGeneration = 0;
const deviceHeaders=()=>({Authorization:'Bearer '+token,'Content-Type':'application/json'});
function clearDeviceReview(){deviceReviewGeneration++;deviceReview=null;el('deviceReview').hidden=true;}
async function loadDevices(){
 if(!token)return;
 const r=await fetch('/api/v1/admin/devices',{headers:deviceHeaders(),cache:'no-store'});
 if(!r.ok){write(el('deviceMessage'),'Sessão expirada ou dispositivos indisponíveis.');return;}
 const devices=(await r.json()).devices;el('deviceList').replaceChildren();
 if(!devices.length){write(el('deviceList'),'Ainda não existem dispositivos associados.');return;}
 for(const device of devices){
  const row=document.createElement('p');const label=document.createElement('span');
  label.textContent=device.label+' · '+(device.revoked?'Revogado':'Autorizado para identificação')+' ';
  row.append(label);
  if(!device.revoked){const button=document.createElement('button');button.type='button';button.textContent='Revogar';
   button.addEventListener('click',async()=>{button.disabled=true;
    try{const result=await fetch('/api/v1/admin/devices/'+encodeURIComponent(device.device_id),{method:'DELETE',headers:deviceHeaders()});
     write(el('deviceMessage'),result.ok?'Dispositivo revogado. As credenciais anteriores deixam de funcionar.':'Não foi possível revogar. Volta a entrar e tenta novamente.');
     await loadDevices();
    }catch{write(el('deviceMessage'),'Ligação interrompida. Atualiza para confirmar o estado.');}
    finally{button.disabled=false;}
   });row.append(button);}
  el('deviceList').append(row);
 }
}
el('deviceLookup').addEventListener('submit',async event=>{
 event.preventDefault();clearDeviceReview();if(!token)return;
 const code=new FormData(event.currentTarget).get('user_code');const generation=deviceReviewGeneration;
 const button=event.currentTarget.querySelector('button');button.disabled=true;
 try{const r=await fetch('/api/v1/admin/devices/inspect',{method:'POST',headers:deviceHeaders(),body:JSON.stringify({user_code:code})});
  if(!r.ok){write(el('deviceMessage'),r.status===429?'Demasiadas tentativas. Aguarda dez minutos.':'Código inválido, expirado ou sessão terminada.');return;}
  const data=await r.json();if(!token||generation!==deviceReviewGeneration)return;deviceReview={code,requestId:data.request_id};
  write(el('deviceDescription'),data.label+' · Código '+code.toUpperCase()+(data.account_id?' · Conta Directory verificada: '+data.account_name+' · '+data.account_id:'')+' · Válido até '+new Date(data.expires_at*1000).toLocaleTimeString('pt-PT'));
  el('deviceApprove').disabled=Boolean(data.account_id&&!data.member_configured);
  el('deviceReview').hidden=false;write(el('deviceMessage'),'Confirma os dados no teu dispositivo antes de aprovar.');
  if(data.account_id){await loadMembers();if(!token||generation!==deviceReviewGeneration)return;el('memberForm').elements.member_subject.value=data.account_id;
   if(!data.member_configured)write(el('deviceMessage'),'Configura primeiro as bibliotecas desta conta na secção Permissões dos familiares. Depois consulta o código novamente e aprova a TV.');}
 }catch{write(el('deviceMessage'),'Não foi possível consultar o código.');}
 finally{button.disabled=false;}
});
// Editing the code cancels the previous review, including pasted replacements.
el('deviceLookup').elements.user_code.addEventListener('input',clearDeviceReview);
async function decideDevice(approve){
 if(!token||!deviceReview)return;const reviewed=deviceReview;clearDeviceReview();
 try{const r=await fetch('/api/v1/admin/devices/decision',{method:'POST',headers:deviceHeaders(),body:JSON.stringify({user_code:reviewed.code,request_id:reviewed.requestId,approve})});
  write(el('deviceMessage'),r.ok?(approve?'Aprovado. Aguarda a confirmação no dispositivo e atualiza a lista.':'Pedido recusado.'):'Pedido expirado ou sessão inválida. Consulta novamente o código.');
  await loadDevices();
 }catch{write(el('deviceMessage'),'Ligação interrompida. Consulta o estado antes de repetir.');}
}
el('deviceApprove').addEventListener('click',()=>decideDevice(true));
el('deviceDeny').addEventListener('click',()=>decideDevice(false));
el('deviceRefresh').addEventListener('click',()=>loadDevices().catch(()=>write(el('deviceMessage'),'Servidor indisponível.')));

let wireguardGeneration=0;
let wireguardExpiry=null;
async function loadWireGuardEnrollments(){
 const session=token;const generation=++wireguardGeneration;if(!session)return;
 clearTimeout(wireguardExpiry);
 for(const title of el('wireguardEnrollments').querySelectorAll('[data-unverified-text]'))title.textContent=title.dataset.unverifiedText;
 write(el('wireguardGateway'),'Gateway por confirmar.');
 const r=await fetch('/api/v1/admin/connect/wireguard/enrollments',{headers:{Authorization:'Bearer '+session},cache:'no-store'});
 if(token!==session||generation!==wireguardGeneration)return;
 if(!r.ok){write(el('wireguardMessage'),'Pedidos indisponíveis. Volta a entrar e atualiza.');return;}
 const data=await r.json();if(token!==session||generation!==wireguardGeneration)return;
 let gateway={state:'not_verified',peers:[]};
 const gatewayRequestStarted=performance.now();
 try{const result=await fetch('/api/v1/admin/connect/wireguard/gateway',{headers:{Authorization:'Bearer '+session},cache:'no-store'});
  if(result.ok)gateway=await result.json();
 }catch{}
 if(token!==session||generation!==wireguardGeneration)return;
 const observed=gateway.state==='configuration_observed'&&gateway.configuration_observed===true;
 const observedIds=new Set(observed?gateway.peers.map(peer=>peer.device_id):[]);
 write(el('wireguardGateway'),observed?'Configuração observada no gateway em '+new Date(gateway.observed_at*1000).toLocaleTimeString('pt-PT')+'. Handshake e acesso remoto ainda por confirmar.':gateway.state==='disabled'?'Serviço de gateway não configurado.':'Sem observação válida do gateway. Acesso remoto desativado.');
 const list=el('wireguardEnrollments');list.replaceChildren();
 const states={pending:'A aguardar aprovação',approved:'Aprovado · gateway por confirmar',revoked:'Revogado'};
 if(!data.enrollments.length)write(list,'Ainda não existem pedidos WireGuard.');
 for(const item of data.enrollments){
  const row=document.createElement('article');const title=document.createElement('p');
  const titleText=item.label+' · '+(item.account_name||'Associação de laboratório')+' · '+states[item.state];
  title.textContent=item.state==='approved'&&observedIds.has(item.device_id)?titleText.replace('gateway por confirmar','configuração observada'):titleText;
  if(item.state==='approved'&&observedIds.has(item.device_id))title.dataset.unverifiedText=titleText;
  row.append(title);
  const identity=document.createElement('p');identity.textContent='TV: '+item.device_id+' · SHA-256: '+item.fingerprint;row.append(identity);
  for(const approve of item.state==='pending'?[true,false]:item.state==='approved'?[false]:[]){
   const button=document.createElement('button');button.type='button';button.textContent=approve?'Aprovar esta chave':'Revogar pedido WireGuard';
   button.addEventListener('click',async()=>{
    if(token!==session||generation!==wireguardGeneration)return;button.disabled=true;
    try{const response=await fetch('/api/v1/admin/connect/wireguard/enrollments/'+encodeURIComponent(item.device_id),{
      method:'POST',headers:{Authorization:'Bearer '+session,'Content-Type':'application/json'},body:JSON.stringify({revision:item.revision,approve})});
     if(token!==session||generation!==wireguardGeneration)return;
     write(el('wireguardMessage'),response.ok?(approve?'Chave aprovada. Gateway por confirmar; acesso remoto desativado.':'Pedido revogado. A associação LAN mantém as permissões existentes.'):'Decisão não confirmada. Atualiza e revê o estado do pedido.');
     await loadWireGuardEnrollments();
    }catch{if(token===session)write(el('wireguardMessage'),'Ligação interrompida. Atualiza para confirmar a decisão.');}
    finally{button.disabled=false;}
   });row.append(button);
  }
  list.append(row);
 }
 if(observed){
  wireguardExpiry=setTimeout(()=>{
   if(token!==session||generation!==wireguardGeneration)return;
   write(el('wireguardGateway'),'Observação do gateway expirada. Atualiza para verificar novamente.');
   for(const title of list.querySelectorAll('[data-unverified-text]'))title.textContent=title.dataset.unverifiedText;
  },Math.max(0,gateway.valid_for_seconds*1000-(performance.now()-gatewayRequestStarted)));
 }
}
el('logout').addEventListener('click',()=>{wireguardGeneration++;clearTimeout(wireguardExpiry);write(el('wireguardGateway'),'Gateway por confirmar.');el('wireguardEnrollments').replaceChildren();});
el('wireguardRefresh').addEventListener('click',()=>loadWireGuardEnrollments().catch(()=>write(el('wireguardMessage'),'Servidor indisponível.')));
el('logout').addEventListener('click',()=>{clearDeviceReview();el('deviceLookup').reset();el('deviceList').replaceChildren();});

// Directory passwords are transient; no destination, path or TLS exception comes from this form.
let directoryGeneration=0;
let directoryBusy=false;
let directoryReady=false;
let directoryCanRenew=false;
function directoryButtons(){
 el('directoryIdentity').disabled=directoryBusy||directoryReady;
 el('directoryRenew').disabled=directoryBusy||!directoryCanRenew;
 for(const button of el('directoryForm').querySelectorAll('button'))button.disabled=directoryBusy||!directoryReady;
}
function showDirectory(data){
 el('directoryActions').hidden=!data.enabled;
 directoryReady=data.identity==='ready';directoryCanRenew=Boolean(data.renewal_available);directoryButtons();
 if(!data.enabled){write(el('directoryStatus'),'Directory desativado. O operador deve configurar o serviço e a confiança TLS localmente.');return;}
 const states={not_checked:'Ainda não verificado',published_at_check:'Publicação aceite na última operação',renewed_at_check:'Renovado na última operação',listed_at_check:'Encontrado na última verificação',not_listed_at_check:'Ausente na última verificação',expired:'Última publicação expirada',recovery_republish_required:'Estado recuperado. Publica novamente com a conta proprietária',invalid_receipt:'Não foi possível validar a publicação guardada',identity_error:'Identidade local inválida'};
 let text=data.origin+' · '+(states[data.state]||'Estado por verificar')+'.';
 if(data.fingerprint)text+=' Identidade: '+data.fingerprint+'.';
 if(data.checked_at)text+=' Observado em '+new Date(data.checked_at*1000).toLocaleString('pt-PT')+'.';
 if(data.expires_at)text+=' Prazo da última publicação: '+new Date(data.expires_at*1000).toLocaleString('pt-PT')+'.';
 if(data.automatic_renewal)text+=' Renovação automática ativa.';
 if(data.renewal_expires_at)text+=' Credencial limitada válida até '+new Date(data.renewal_expires_at*1000).toLocaleString('pt-PT')+'.';
 write(el('directoryStatus'),text+' Este estado é uma observação anterior; não confirma disponibilidade atual nem autoriza media.');
}
async function loadDirectory(){
 if(!token)return;const session=token;const generation=directoryGeneration;
 const r=await fetch('/api/v1/admin/directory',{headers:{Authorization:'Bearer '+session},cache:'no-store'});
 const data=await r.json();
 if(token!==session||generation!==directoryGeneration)return;
 if(r.ok)showDirectory(data);else write(el('directoryMessage'),'Não foi possível consultar o Directory.');
}
async function directoryAction(action){
 if(!token||directoryBusy)return;
 const form=el('directoryForm');let payload;
 if(!['identity','renew'].includes(action)){
  if(!form.reportValidity())return;
  payload={username:form.elements.directory_username.value,password:form.elements.directory_password.value};
  if(action==='publish')payload.name=form.elements.directory_name.value;
 }
 form.elements.directory_password.value='';
 const session=token;const generation=++directoryGeneration;directoryBusy=true;directoryButtons();
 write(el('directoryMessage'),'A executar operação no Directory…');
 try{
  const r=await fetch('/api/v1/admin/directory/'+action,{method:'POST',headers:{Authorization:'Bearer '+session,'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined});
  const data=await r.json();if(token!==session||generation!==directoryGeneration)return;
  if(!r.ok){const messages={directory_busy:'Já existe uma operação em curso.',directory_account_changed:'Usa a conta Directory originalmente associada a este servidor.',directory_revision_changed:'A revisão do servidor mudou. Verifica a identidade antes de continuar.',directory_identity_restore_required:'Falta a chave de uma identidade já associada. Recupera a chave original antes de continuar.'};
   write(el('directoryMessage'),r.status===401?'Sessão NOVA expirada. Volta a entrar.':r.status===429?'Demasiadas operações. Aguarda antes de repetir.':messages[data.detail]||'Operação recusada. Confirma a conta, a palavra-passe, a identidade e a disponibilidade do Directory.');return;}
  showDirectory(data);write(el('directoryMessage'),action==='identity'?'Identidade inicializada. Já podes publicar.':action==='publish'?'Publicação aceite. A renovação usa uma credencial limitada; verifica o estado acima.':action==='renew'?'Renovação confirmada sem palavra-passe administrativa.':'Verificação concluída.');
 }catch{if(token===session&&generation===directoryGeneration)write(el('directoryMessage'),'Ligação interrompida. Verifica o estado antes de repetir.');}
 finally{payload=null;if(generation===directoryGeneration){directoryBusy=false;directoryButtons();}}
}
el('directoryForm').addEventListener('submit',event=>{event.preventDefault();directoryAction('publish');});
el('directoryCheck').addEventListener('click',()=>directoryAction('check'));
el('directoryIdentity').addEventListener('click',()=>directoryAction('identity'));
el('directoryRenew').addEventListener('click',()=>directoryAction('renew'));
el('logout').addEventListener('click',()=>{directoryGeneration++;directoryBusy=false;directoryReady=false;directoryCanRenew=false;el('directoryForm').reset();el('directoryActions').hidden=true;write(el('directoryStatus'),'');write(el('directoryMessage'),'');});

function showMemberLibraries(){
 const target=el('memberLibraries');target.replaceChildren();
 for(const library of libraryChoices){const label=document.createElement('label');const input=document.createElement('input');
  input.type='checkbox';input.name='member_libraries';input.value=library.id;label.append(input,document.createTextNode(' '+library.name));target.append(label);}
 if(!libraryChoices.length)write(target,'Conclui e verifica a configuração Jellyfin para escolher bibliotecas.');
}
async function loadMembers(){
 if(!token)return;const session=token;
 const r=await fetch('/api/v1/admin/members',{headers:{Authorization:'Bearer '+session},cache:'no-store'});
 if(!r.ok||token!==session)return;const data=await r.json();if(token!==session)return;
 const select=el('memberForm').elements.member_subject;const selected=select.value;select.replaceChildren();el('memberList').replaceChildren();
 for(const member of data.members){
  const option=document.createElement('option');option.value=member.subject;option.textContent=member.username+' · '+member.subject;select.append(option);
  const row=document.createElement('p');row.textContent=member.username+' · '+(member.disabled?'Sem autorização ativa':member.libraries.map(lib=>lib.name).join(' · '));
  if(!member.disabled){const button=document.createElement('button');button.type='button';button.textContent='Revogar conta e dispositivos';
   button.addEventListener('click',async()=>{button.disabled=true;
    try{const result=await fetch('/api/v1/admin/members/'+encodeURIComponent(member.subject),{method:'DELETE',headers:{Authorization:'Bearer '+token}});
     write(el('memberMessage'),result.ok?'Conta revogada. Os dispositivos perdem autorização.':'Não foi possível revogar.');await loadMembers();await loadDevices();
    }catch{write(el('memberMessage'),'Ligação interrompida. Atualiza o estado.');}finally{button.disabled=false;}
   });row.append(' ',button);}
  el('memberList').append(row);
 }
 if([...select.options].some(option=>option.value===selected))select.value=selected;
}
el('memberForm').addEventListener('submit',async event=>{
 event.preventDefault();if(!token)return;const form=event.currentTarget;const data=new FormData(form);
 const payload={subject:data.get('member_subject'),libraries:data.getAll('member_libraries'),username:data.get('member_admin'),password:data.get('member_password')};
 form.elements.member_password.value='';if(!payload.subject||!payload.libraries.length){write(el('memberMessage'),'Seleciona a conta e pelo menos uma biblioteca.');return;}
 const session=token;const button=form.querySelector('button');button.disabled=true;
 write(el('memberMessage'),'A criar/verificar o utilizador Jellyfin limitado…');
 try{const result=await fetch('/api/v1/admin/members',{method:'POST',headers:{Authorization:'Bearer '+session,'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(token!==session)return;
  if(!result.ok){write(el('memberMessage'),'Permissões não aplicadas. Verifica a conta administrativa Jellyfin, as bibliotecas e o estado do serviço. O acesso fica bloqueado até concluir.');return;}
  clearDeviceReview();write(el('memberMessage'),'Permissões verificadas. Consulta novamente o código da TV e aprova o dispositivo.');await loadMembers();
 }catch{if(token===session)write(el('memberMessage'),'Ligação interrompida. Verifica o estado antes de repetir.');}
 finally{payload.password='';button.disabled=false;}
});
el('logout').addEventListener('click',()=>{el('memberForm').reset();el('memberList').replaceChildren();el('memberForm').elements.member_subject.replaceChildren();write(el('memberMessage'),'');});
