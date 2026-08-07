let state=null;
let chatHistory=[];
let chatHydrated=false;
let onboardingFlowStep=0;
let onboardingFlowTouched=false;
let businessContextQuestionIndex=0;
let destinationAutoDiscoveryKey='';
let dailyBriefTimezoneSyncStarted=false;
let updateCheckStarted=false;
let updateCheckInFlight=false;
let updateLastCheckedAt=0;
let updateInfo=null;
let updateCheckError='';
let updateAutoTimer=null;
const UPDATE_INSTALLED_ACK_KEY='dashboardUpdateInstalledVersion';
const UPDATE_CHECK_COOLDOWN_MS=60*1000;
const UPDATE_CHECK_POLL_MS=60*1000;
const ONBOARDING_STEP_KEY='dashboardOnboardingStepId';
const fmtMoney=n=>'$'+Number(n||0).toLocaleString(undefined,{maximumFractionDigits:2});
const fmtPct=n=>Number(n||0).toFixed(2)+'%';
const qs=s=>document.querySelector(s);
const urlParams=new URLSearchParams(window.location.search);
function isLocalWorkbenchHost(host){
 return host==='127.0.0.1'||host==='localhost'||host==='0.0.0.0'||host.startsWith('192.168.')||host.startsWith('10.')||/^172\.(1[6-9]|2\d|3[0-1])\./.test(host);
}
function readUiWorkbenchPreview(){
 const forced=urlParams.get('ui_preview');
 if(forced==='1')return true;
 if(forced==='0'||urlParams.get('full_setup')==='1')return false;
 const saved=localStorage.getItem('dashboardUiPreview');
 if(saved==='1')return true;
 return false;
}
let lang=localStorage.getItem('dashboardLang')||'es';
let dashboardView=localStorage.getItem('dashboardView')||'control';
let metricsRange={preset:'maximum',since:'',until:''};
let metricsRangeTouched=false;
let metricsCustomOpen=false;
function normalizeDashboardTheme(value){
 if(value==='light')return 'aurora';
 if(value==='dark')return 'sapphire';
 return value==='sapphire'||value==='ember'?value:'aurora';
}
let dashboardTheme=normalizeDashboardTheme(localStorage.getItem('dashboardTheme')||'aurora');
let uiWorkbenchPreview=readUiWorkbenchPreview();
const copy={
 en:{
	  brand_subtitle:'Self-hosted local/VPS operator for Meta Ads',zone_brief:'Profile and daily read',zone_work:'Campaign workspace',zone_actions:'Approvals and activity',control_center:'Control Center',control_subtitle:'Daily decisions, risk signals, and ad account health in one place.',safe_mode:'Approval protection active',ask_agent:'Ask agent',ask_manager:'Ask manager',chat_fab:'Talk to agent',chat_title:'Admira IA Manager',chat_subtitle:'Ask for catchups, actions, or explanations.',new_chat:'New chat',quick_status:'Where are we?',quick_budget:'Review budget',quick_fatigue:'Check fatigue',send:'Send',usage_guide:'Guide',tab_overview:'Overview',tab_setup:'Setup',tab_creator:'Create campaign',tab_audiences:'Audiences',tab_creatives:'Creatives',tab_reports:'Reports',updated:'Updated',version:'Version',new_brief:'New',daily_brief:'Daily Brief',run:'Refresh',fatigue_monitor:'Fatigue Monitor',setup_status:'Setup Status',setup_form_title:'Buyer setup fields',setup_form_body:'Save the few account details the assistant needs. No technical file editing here.',license_panel_title:'Lifetime license',license_panel_body:'Your license is lifetime. This device verifies it automatically with our server without asking for the code again.',license_active:'Active',license_missing:'Missing',license_invalid:'Needs attention',license_cloud:'Cloud validation',license_local:'Local license',license_activate:'Activate license',license_key:'License key',buyer_email:'Buyer email',ad_account_id:'Ad account',page_id:'Facebook page',instagram_actor_id:'Instagram profile',default_adset_id:'Advanced field',landing_url:'Website link',save_setup:'Save',refresh:'Refresh',campaign_creator:'Create a campaign',creator_kicker:'New campaign',creator_title:'Create a campaign',creator_body:'Tell the agent what you sell, who should see it, and how much you can spend. It will organize the campaign and show it to you before anything can spend money.',creator_chat_cta:'Create by talking to the agent',paused_draft_title:'You decide before money is spent',paused_draft_body:'The agent prepares the campaign and asks for your approval. If you choose to leave it active, it can start spending only after you approve it.',creator_manual_title:'I prefer to enter the details myself',creator_manual_help:'Optional: the agent can ask you these questions in chat.',creator_basic:'What will you advertise?',campaign_name_simple:'Name for this campaign',campaign_name_example:'Example: June promotion',campaign_goal_simple:'What should people do?',goal_purchases:'Buy',goal_contacts:'Leave their details',goal_action:'Take an action on your website',landing_url_simple:'Page people will visit',landing_url_example:'https://your-page.com',primary_text_simple:'Message people will read',primary_text_example:'Example: Discover how this offer can help you today.',headline_simple:'Short title',headline_example:'Example: See the offer',image_simple:'Image already prepared, if you have one',image_path_example:'Optional: image file path',creator_people_budget:'Who will see it and how much can it spend?',daily_budget_simple:'Maximum to spend each day',total_budget_simple:'Maximum to spend in total',locations_simple:'Where those people live',locations_example:'Example: Colombia, Mexico, or Miami',interests_simple:'Things they may be interested in',interests_example:'Example: online stores, beauty, education',age_min_simple:'Youngest age',age_max_simple:'Oldest age',creator_decision:'How should it be prepared?',creative_variations_simple:'How many ideas to compare?',compare_options_simple:'Compare those ideas?',compare_yes:'Yes, compare them',compare_no:'No, use one idea',after_approval_simple:'After you approve it',active_after_approval:'Start showing the ads and spending the chosen budget',ready_not_spending:'Leave it ready without spending',confirm_active_spend:'Only if I choose to turn it on: I understand that after approving, this campaign may start spending my chosen budget.',creator_meta_optional:'Only if you already know this Meta detail',pixel_optional:'Meta tracking number (Pixel ID), optional',creator_review_notice:'If it stays paused, Admira can create it without spending. Activation still needs your approval.',audience_builder:'Audience Builder',what_sell:'What do you sell?',who_buys:'Who buys today?',audience_product_example:'Example: an online course or beauty product',audience_buyer_example:'Example: people who want to sell more',audience_locations_example:'Example: Colombia or Mexico',audience_interests_example:'Example: beauty, education, local stores',audience_data_example:'Example: people who messaged on Instagram or buyers',age_range:'Age range',budget_level:'Budget level',budget_small:'Small',budget_medium:'Medium',budget_large:'Large',data_sources:'Data sources',consent_upload:'I have consent to use customer emails/phones if I upload them later.',notes:'Notes',optional:'Optional',build_audience:'Build Audience Strategy',lookalike_status:'Lookalike status',recommended_audiences:'Recommended audiences',next_steps:'Next steps',name:'Name',objective:'Objective',daily_budget:'Daily Budget',total_budget:'Total Budget',locations:'Locations',interests:'Interests',age_min:'Age Min',age_max:'Age Max',creative_variations:'Creative Variations',ab_test:'A/B Test',enabled:'Enabled',disabled:'Disabled',stage_campaign:'Prepare / create paused',creative_refresh:'Creative Refresh',generate_drafts:'Generate Drafts',upload_payloads:'Upload Payloads',campaign_comparison:'Campaign Comparison',export_csv:'Export CSV',campaign:'Campaign',status:'Status',budget_optimizer:'Budget Optimizer',now:'Now',rec:'Rec',pending_approvals:'Pending Approvals',action_log:'Action Log',
  targeting_picker_title:'Choose the audience with Meta options',targeting_picker_body:'Search locations and interests from Meta, or let the agent suggest the safest audience.',targeting_agent_cta:'Ask the agent',targeting_broad_title:'Broad audience',targeting_broad_body:'Best default: age, location, creative and Meta learning.',targeting_guided_title:'Guided interests',targeting_guided_body:'Use Meta interests as hints when the niche is clear.',targeting_warm_title:'Retargeting / lookalike',targeting_warm_body:'Only when pixel, page, Instagram or customer data is ready.',targeting_search:'Search Meta',targeting_manual_fallback:'If Meta search is not available',targeting_no_results:'No Meta options found. Try another word.',targeting_need_query:'Write what you want to search first.',
  spend:'Spend',revenue:'Revenue',conversions:'Conversions',active_budget:'Active Budget',active_daily_budget:'Active daily budget',roas:'ROAS',cpa:'CPA',ctr:'CTR',cpc:'CPC',frequency:'Frequency',mode:'Protection',ok:'OK',warnings:'Warnings',blocked:'Blocked',live_ready:'Meta ready',
  spend_tip:'How much money has been spent on ads in this period.',revenue_tip:'How much sales value the ads are estimated to have produced.',conversions_tip:'How many desired actions happened, such as purchases, leads, or signups.',active_budget_tip:'The total daily budget still running across active campaigns.',active_daily_budget_tip:'The total daily ad budget currently running across active campaigns.',daily_budget_tip:'How much the campaign is allowed to spend per day.',roas_tip:'Return on ad spend. If ROAS is 3x, every $1 in ads brought about $3 back.',cpa_tip:'Cost per acquisition. This is roughly what you paid to get one conversion.',ctr_tip:'Click-through rate. The percent of people who saw the ad and clicked it.',cpc_tip:'Cost per click. The average amount paid for one click.',frequency_tip:'How many times the average person has seen the ad. High frequency can mean people are getting tired of it.',mode_tip:'Protected actions use approval: Admira can create paused setups, but activation and spending need your green light.',ok_tip:'Items already configured correctly.',warnings_tip:'Items that are not blocking the demo, but should be reviewed before going live.',blocked_tip:'Items that must be fixed before the full live workflow can run.',live_ready_tip:'Whether the install has the key pieces needed to prepare Meta Ads and request activation approval.',
  no_fatigue:'No fatigue triggers right now.',no_pending:'No pending approvals.',no_actions:'No actions logged yet.',no_creatives:'No creative refresh drafts yet.',no_uploads:'No upload payloads staged yet.',request:'Request',apply:'Apply',approve:'Approve',stage_v1_upload:'Stage v1 Upload',missing:'Missing',variants:'variants',increase_budget:'Increase budget',adjust_budget:'Adjust budget',refresh_creative:'Refresh creative',pause:'Pause',resume:'Resume',details:'Details',
  q_track:'Am I on track?',q_running:"What's running?",q_performance:"How's performance?",q_winners:"Who's winning or losing?",q_fatigue:'Any fatigue?',
	  live_ready_yes:'Yes',live_ready_no:'No',check:'Check',draft_where_are_we:'Give me a business catch-up: where are we today, what should I watch, and what would you do next?',draft_catchup:'Explain today’s daily brief like my Meta Ads manager. What matters most?',draft_fatigue:'Review fatigue risk. Which ads need new creative and why?',draft_budget:'Review the budget optimizer. Which recommendations are safe and which need caution?',draft_setup:'Review setup status. What is missing before you can prepare campaigns and approve activation safely?',draft_audience:'Help me choose targeting. Ask me only what is missing, then recommend broad, interest, retargeting, and lookalike options safely.',chat_welcome:'Hi, I’m your Meta Ads manager. Ask me for a catch-up, a decision, or help taking an action.',chat_summary:'Here is the catch-up: account ROAS is {roas}x, CPA is {cpa}, active budget is {budget}, and {pending} approval(s) are pending. The safest next step is to review budget recommendations and fatigue before going live.',chat_budget:'Budget view: compare current vs suggested budgets. For winning campaigns, scale carefully; for weak campaigns, fix creative or pause before adding spend.',chat_fatigue:'Fatigue view: watch frequency, CTR drops, and rising CPC. If fatigue is present, generate creative refresh drafts before increasing budget.',chat_setup:'Setup view: check blocked items first. Activation, spending and publishing stay protected by approval.',chat_action_hint:'I can open the right workflow from here. For live account changes, the approval queue and dashboard password still protect the account.',toast_resume:'Resume staged for approval',toast_action:'Action complete',toast_budget:'Budget action recorded',toast_daily:'Daily agent report generated',toast_export:'CSV exported: ',toast_approval:'Approval executed',toast_refresh:'Creative refresh draft generated',toast_upload:'Upload payload staged',toast_audience:'Audience strategy generated',toast_setup_saved:'Setup fields saved',toast_license:'License checked',toast_details:'Campaign details visible on this card.',prompt_budget:'New daily budget',unlock_title:'Unlock dashboard',unlock_body:'Enter the password for this dashboard to continue.',unlock_create_title:'Create your password',unlock_create_body:'This is your private password for this dashboard on this computer or server. You choose it now; we do not send one to you.',dashboard_password:'Dashboard password',dashboard_password_confirm:'Repeat password',remember_device:'Remember this device',unlock_button:'Unlock dashboard',unlock_create_button:'Save my password',unlock_needed:'Enter the password for this dashboard to continue.',unlock_create_needed:'Create a password to protect this dashboard before continuing.',unlock_failed:'That password did not unlock the dashboard. Try again.',dashboard_password_short:'Use at least 8 characters.',dashboard_password_mismatch:'Passwords do not match.',copy_command:'Copy',copied:'Copied'
 },
 es:{
	  brand_subtitle:'Operador local/VPS para Meta Ads',zone_brief:'Perfil y lectura',zone_work:'Área de campañas',zone_actions:'Aprobaciones y actividad',control_center:'Centro de control',control_subtitle:'Decisiones diarias, señales de riesgo y salud de la cuenta en un solo lugar.',safe_mode:'Protección por aprobación activa',ask_agent:'Preguntar',ask_manager:'Hablar con el agente',chat_fab:'Hablar con el agente',chat_title:'Manager de Admira IA',chat_subtitle:'Pide resumen, decisiones o acciones.',new_chat:'Nuevo chat',quick_status:'¿Dónde estamos?',quick_budget:'Revisar presupuesto',quick_fatigue:'Ver cansancio',send:'Enviar',usage_guide:'Guía',tab_overview:'Resumen',tab_setup:'Configuración',tab_creator:'Crear campaña',tab_audiences:'Audiencias',tab_creatives:'Creativos',tab_reports:'Reportes',updated:'Actualizado',version:'Versión',new_brief:'Nuevo',daily_brief:'Resumen diario',run:'Actualizar',fatigue_monitor:'Cansancio de anuncios',setup_status:'Configuración y seguridad',setup_form_title:'Datos importantes guardados',setup_form_body:'Aquí puedes cambiar licencia, cuenta, página y web. Normalmente esto ya queda listo en la configuración inicial. Si no sabes qué poner, pregúntale al agente.',license_panel_title:'Activación de licencia',license_panel_body:'Tu licencia es de por vida. Este equipo la confirma automáticamente con nuestro servidor sin volver a pedirte el código.',license_active:'Activa',license_missing:'Falta',license_invalid:'Revisar',license_cloud:'Confirmada online',license_local:'Licencia local',license_activate:'Activar licencia',license_key:'Licencia',buyer_email:'Email del comprador',ad_account_id:'Cuenta publicitaria',page_id:'Página de Facebook',instagram_actor_id:'Perfil de Instagram',default_adset_id:'Campo avanzado',landing_url:'Link de tu web',save_setup:'Guardar',refresh:'Actualizar',campaign_creator:'Crear una campaña',creator_kicker:'Nueva campaña',creator_title:'Crea una campaña',creator_body:'Cuéntale al agente qué vendes, quién debe verlo y cuánto puedes gastar. Él organizará la campaña y te la mostrará antes de que pueda gastar dinero.',creator_chat_cta:'Crear hablando con el agente',paused_draft_title:'Tú decides antes de gastar dinero',paused_draft_body:'El agente prepara la campaña y te pide aprobación. Si decides dejarla activa, solo podrá empezar a gastar después de que la apruebes.',creator_manual_title:'Prefiero escribir los datos yo',creator_manual_help:'Opcional: el agente puede preguntarte todo esto en el chat.',creator_basic:'Qué vas a anunciar',campaign_name_simple:'Nombre para esta campaña',campaign_name_example:'Ej: Promo de junio',campaign_goal_simple:'Qué quieres que haga la persona',goal_purchases:'Comprar',goal_contacts:'Dejar sus datos',goal_action:'Hacer una acción en tu página',landing_url_simple:'Página que visitarán',landing_url_example:'https://tu-pagina.com',primary_text_simple:'Mensaje que leerán',primary_text_example:'Ej: Descubre cómo esta oferta puede ayudarte hoy.',headline_simple:'Título corto',headline_example:'Ej: Mira la oferta',image_simple:'Imagen ya preparada, si tienes una',image_path_example:'Opcional: ruta del archivo de imagen',creator_people_budget:'Quién lo verá y cuánto puede gastar',daily_budget_simple:'Máximo que puede gastar al día',total_budget_simple:'Máximo que puede gastar en total',locations_simple:'Dónde viven esas personas',locations_example:'Ej: Colombia, México o Miami',interests_simple:'Qué cosas podrían interesarles',interests_example:'Ej: tiendas online, belleza, educación',age_min_simple:'Edad más joven',age_max_simple:'Edad mayor',creator_decision:'Cómo quieres dejarla preparada',creative_variations_simple:'Cuántas ideas quieres comparar',compare_options_simple:'Comparar esas ideas',compare_yes:'Sí, compararlas',compare_no:'No, usar una sola idea',after_approval_simple:'Después de que la apruebes',active_after_approval:'Empezar a mostrar anuncios y gastar el presupuesto elegido',ready_not_spending:'Dejarla lista sin gastar',confirm_active_spend:'Marcar solo si elegiste empezar a mostrar anuncios: entiendo que, después de aprobar, esta campaña podrá gastar el presupuesto que elegí.',creator_meta_optional:'Solo si ya conoces este dato de Meta',pixel_optional:'Número de seguimiento de Meta (Pixel ID), opcional',creator_review_notice:'Si queda en pausa, Admira puede crearla sin gastar. Activarla siempre pide tu aprobación.',audience_builder:'Elegir público',what_sell:'¿Qué vendes?',who_buys:'¿Quién compra hoy?',audience_product_example:'Ej: un curso o un producto de belleza',audience_buyer_example:'Ej: personas que quieren vender más',audience_locations_example:'Ej: Colombia o México',audience_interests_example:'Ej: belleza, educación o negocios locales',audience_data_example:'Ej: personas que escribieron por Instagram o compradores',age_range:'Edad aproximada',budget_level:'Tamaño del presupuesto',budget_small:'Pequeño',budget_medium:'Mediano',budget_large:'Grande',data_sources:'Datos que ya tienes',consent_upload:'Tengo permiso para usar emails/teléfonos de clientes si los subo después.',notes:'Notas',optional:'Opcional',build_audience:'Crear recomendación de público',lookalike_status:'Público parecido',recommended_audiences:'A quién mostrar anuncios',next_steps:'Siguientes pasos',name:'Nombre',objective:'Objetivo',daily_budget:'Presupuesto diario',total_budget:'Presupuesto total',locations:'Países/ubicaciones',interests:'Intereses',age_min:'Edad mínima',age_max:'Edad máxima',creative_variations:'Opciones de anuncios',ab_test:'Comparar ideas',enabled:'Activada',disabled:'Desactivada',stage_campaign:'Preparar / crear en pausa',creative_refresh:'Crear ideas nuevas',generate_drafts:'Crear ideas',upload_payloads:'Anuncios listos para revisar',campaign_comparison:'Comparación de campañas',export_csv:'Descargar reporte',campaign:'Campaña',status:'Estado',budget_optimizer:'Qué hacer con el presupuesto',now:'Actual',rec:'Sugerido',pending_approvals:'Decisiones por aprobar',action_log:'Lo que hizo el agente',
  targeting_picker_title:'Elige público con opciones de Meta',targeting_picker_body:'Busca países, ciudades o intereses reales de Meta. Si no sabes qué elegir, pídeselo al agente.',targeting_agent_cta:'Preguntar al agente',targeting_broad_title:'Público amplio',targeting_broad_body:'Buen punto de partida: país, edad y buenos anuncios. Meta aprende con señales.',targeting_guided_title:'Intereses simples',targeting_guided_body:'Úsalos como pistas cuando sabes qué temas le importan a tu cliente.',targeting_warm_title:'Personas que ya te conocen / parecidos',targeting_warm_body:'Solo cuando ya tienes visitas, Instagram activo o clientes con permiso.',targeting_search:'Buscar en Meta',targeting_manual_fallback:'Solo si el buscador no funciona',targeting_no_results:'No encontré opciones en Meta. Prueba otra palabra.',targeting_need_query:'Escribe primero qué quieres buscar.',
  spend:'Gasto',revenue:'Ingresos',conversions:'Conversiones',active_budget:'Presupuesto activo',active_daily_budget:'Presupuesto diario activo',roas:'ROAS',cpa:'CPA',ctr:'CTR',cpc:'CPC',frequency:'Frecuencia',mode:'Protección',ok:'Listo',warnings:'Revisar',blocked:'Falta arreglar',live_ready:'Meta listo?',
  spend_tip:'Dinero que ya se gastó en anuncios.',revenue_tip:'Ventas o valor que los anuncios parecen haber producido.',conversions_tip:'Acciones importantes: compras, formularios, registros u otro objetivo.',active_budget_tip:'Dinero máximo por día que sigue encendido en campañas activas.',active_daily_budget_tip:'Dinero máximo por día que puede gastarse ahora.',daily_budget_tip:'Máximo que una campaña puede gastar por día.',roas_tip:'Cuánto vuelve por cada $1 gastado. ROAS 3x significa que $1 trajo aprox. $3.',cpa_tip:'Cuánto cuesta conseguir una compra, lead o acción importante.',ctr_tip:'De cada 100 personas que ven el anuncio, cuántas hacen clic.',cpc_tip:'Cuánto pagas por cada clic.',frequency_tip:'Cuántas veces ve una persona el mismo anuncio. Si sube mucho, puede cansarse.',mode_tip:'Acciones protegidas usan aprobación: Admira puede crear en pausa, pero activar y gastar necesitan tu luz verde.',ok_tip:'Esto ya está bien.',warnings_tip:'No es urgente, pero conviene revisarlo.',blocked_tip:'Esto falta antes de usar todo el producto.',live_ready_tip:'Dice si ya puede preparar anuncios en Meta y pedir aprobación para activarlos.',
  no_fatigue:'No hay señales de cansancio de anuncios por ahora.',no_pending:'No hay aprobaciones pendientes.',no_actions:'Todavía no hay acciones registradas.',no_creatives:'Todavía no hay ideas de anuncios.',no_uploads:'Todavía no hay imágenes preparadas para publicar.',request:'Solicitar',apply:'Aplicar',approve:'Aprobar',stage_v1_upload:'Preparar para publicar',missing:'Falta',variants:'opciones',increase_budget:'Subir presupuesto',adjust_budget:'Ajustar presupuesto',refresh_creative:'Probar imagen nueva',pause:'Pausar',resume:'Reactivar',details:'Detalles',
  q_track:'¿Voy bien?',q_running:'¿Qué está corriendo?',q_performance:'¿Cómo va el rendimiento?',q_winners:'¿Qué gana y qué pierde?',q_fatigue:'¿Se está cansando algún anuncio?',
	  live_ready_yes:'Sí',live_ready_no:'No',check:'Revisar',draft_where_are_we:'Dame un resumen del negocio: dónde estamos hoy, qué debo vigilar y qué harías después.',draft_catchup:'Explícame el resumen diario como mi manager de Meta Ads. ¿Qué es lo más importante?',draft_fatigue:'Revisa el riesgo de cansancio del anuncio. ¿Qué anuncios necesitan una imagen o texto nuevo y por qué?',draft_budget:'Revisa el presupuesto. ¿Qué recomendaciones son seguras y cuáles requieren cuidado?',draft_setup:'Revisa el estado de configuración. ¿Qué falta para preparar campañas y aprobar activación con seguridad?',draft_audience:'Ayúdame a elegir a quién mostrar anuncios. Pregúntame solo lo que falte y dime si conviene llegar a personas nuevas, personas que ya me conocen o personas parecidas a mis clientes.',chat_welcome:'Hola, soy tu manager de Meta Ads. Pídeme un resumen, una decisión o ayuda para ejecutar una acción.',chat_summary:'Resumen: por cada $1 invertido regresan {roas}; conseguir una compra cuesta {cpa}; el presupuesto activo es {budget} y hay {pending} decisión(es) pendientes. El siguiente paso más seguro es revisar presupuesto y cansancio antes de aumentar gasto.',chat_budget:'Presupuesto: compara el presupuesto actual contra el sugerido. En campañas ganadoras, aumenta con cuidado; en campañas débiles, prueba otra imagen o texto o pausa antes de invertir más.',chat_fatigue:'Cansancio del anuncio: revisa si muchas personas ven el mismo anuncio, si bajan los clics o si cada clic cuesta más. Si pasa, crea nuevas imágenes o textos antes de subir presupuesto.',chat_setup:'Configuración: resuelve primero lo que falta. Activar, gastar y publicar quedan protegidos por aprobación exacta.',chat_action_hint:'Puedo abrir el paso correcto desde aquí. Para cambios reales, tus decisiones y la contraseña del dashboard protegen la cuenta.',toast_resume:'Reactivación enviada a aprobación',toast_action:'Acción completada',toast_budget:'Acción de presupuesto registrada',toast_daily:'Resumen diario generado',toast_export:'Reporte descargado: ',toast_approval:'Aprobación ejecutada',toast_refresh:'Ideas de anuncio creadas',toast_upload:'Imagen preparada para revisar',toast_audience:'Recomendación de público creada',toast_setup_saved:'Configuración guardada',toast_license:'Licencia revisada',toast_details:'Los detalles clave están visibles en esta tarjeta.',prompt_budget:'Nuevo presupuesto diario',unlock_title:'Desbloquear dashboard',unlock_body:'Escribe la contraseña de este dashboard para continuar.',unlock_create_title:'Crea tu contraseña',unlock_create_body:'Esta será tu contraseña privada para proteger este dashboard en este equipo o servidor. La eliges tú ahora; nosotros no te enviamos una.',dashboard_password:'Contraseña del dashboard',dashboard_password_confirm:'Repetir contraseña',remember_device:'Recordar este dispositivo',unlock_button:'Desbloquear dashboard',unlock_create_button:'Guardar mi contraseña',unlock_needed:'Escribe la contraseña de este dashboard para continuar.',unlock_create_needed:'Crea una contraseña para proteger este dashboard antes de seguir.',unlock_failed:'Esa contraseña no desbloqueó el dashboard. Intenta de nuevo.',dashboard_password_short:'Usa al menos 8 caracteres.',dashboard_password_mismatch:'Las contraseñas no coinciden.',copy_command:'Copiar',copied:'Copiado'
 }
};
const labelKeys={Spend:'spend',Revenue:'revenue',Conversions:'conversions','Active Budget':'active_budget',ROAS:'roas',CPA:'cpa',CTR:'ctr',CPC:'cpc',Frequency:'frequency',frequency:'frequency',conversions:'conversions','Active daily budget':'active_daily_budget','active daily budget':'active_daily_budget','daily budget':'daily_budget',Mode:'mode',OK:'ok',Warnings:'warnings',Blocked:'blocked','Live Ready':'live_ready'};
const questionKeys={'Am I on track?':'q_track',"What's running?":'q_running',"How's performance?":'q_performance',"Who's winning/losing?":'q_winners',"Who's winning or losing?":'q_winners','Any fatigue?':'q_fatigue'};
const esText={
 Files:'Instalación',Runtime:'Funcionamiento',Security:'Protección','Meta Live Requirements':'Conexión con Meta','Creative Generation':'Imágenes de anuncios','Agent Chat':'Chat con el agente',Telegram:'Telegram','Upload Readiness':'Publicación de anuncios',Scheduler:'Lectura diaria automática',
 '.env config':'Llaves locales guardadas','ad-config.json':'Datos de anuncios guardados','Metrics cache':'Datos del dashboard','Dashboard script':'Pantalla del dashboard','Daily agent script':'Agente diario','Agent mode':'Nivel de control','Primary connector':'Conexión principal','Meta execution path':'Conexión con Meta','Latest daily report':'Última lectura diaria','Latest action log':'Última acción registrada','Dashboard bind host':'Dónde se abre el dashboard','Dashboard write token':'Contraseña del dashboard','Dashboard password':'Contraseña del dashboard','Token required for writes':'Contraseña requerida para acciones','Password required for actions':'Contraseña requerida para acciones','License key':'Licencia','Public dashboard opt-in':'Acceso público permitido','Live-action kill switch':'Permiso de activación','.env permissions':'Protección de llaves','Dashboard data permissions':'Protección de datos del dashboard','Output permissions':'Protección de archivos creados','Logs permissions':'Protección de registros','Meta ad account':'Cuenta publicitaria de Meta','Direct Graph token':'Clave de acceso de Meta','Meta token':'Clave de acceso de Meta','Page ID':'Página de Facebook','Landing page URL':'Web de destino','Creative refresh enabled':'Ideas nuevas de anuncios activas','Image generation path':'Ruta de imágenes','Codex/Image login':'Codex/Image para creativos','Codex CLI':'Codex para creativos','Codex creative bridge (optional local-agent access)':'Codex creativo opcional','Brand guide files':'Memoria de marca','Agent chat provider':'Motor del chat','Agent base installed':'Base del agente instalada','Agent ChatGPT/Codex login':'ChatGPT/Codex conectado','OpenAI-compatible model':'Modelo externo compatible','Agent chat model':'Modelo del chat','MiniMax fallback':'Plan B del chat','MiniMax API key':'Clave de MiniMax','Agent profile files':'Personalidad del agente','Telegram agent access':'Chat por Telegram','Telegram bot':'Bot de Telegram','Allowed Telegram chat':'Tu chat privado de Telegram','Upload staging index':'Anuncios preparados','Latest upload payload':'Última publicación preparada','Cron setup script':'Lectura diaria automática','VPS systemd setup script':'Servicio en servidor','Logs directory':'Registros del sistema',
 'No daily report yet.':'Todavía no hay lectura diaria.','No actions logged yet.':'Todavía no hay acciones registradas.','Connect Meta from the dashboard setup.':'Falta terminar la conexión con Meta. Sigue el paso de Meta en la configuración inicial.','Recommended: connect Meta from setup':'Recomendado: seguir el paso de conexión con Meta','configured':'configurado','Configured inside agent':'Listo dentro del agente','No usado; el chat usa una API compatible OpenAI.':'No usado; el chat usa el modelo externo configurado.','Agent base not installed':'Falta la base del agente','Agent selected model':'Modelo elegido del agente','Optional fallback not configured':'Plan B opcional no configurado','Optional unless AGENT_CHAT_PROVIDER is minimax/openai_compatible/openai.':'Opcional si usas ChatGPT/Codex.','Missing AGENT_CHAT_API_KEY, AGENT_CHAT_BASE_URL, or AGENT_CHAT_MODEL':'Falta clave, URL o nombre del modelo externo.','Missing DASHBOARD_TOKEN':'Falta contraseña del dashboard','Missing DASHBOARD_PASSWORD':'Falta contraseña del dashboard','License key missing':'Falta la licencia','Invalid license format':'La licencia no se ve correcta','License checksum mismatch':'La licencia no pasó validación','License active':'Licencia activa','Lifetime license active':'Licencia activa de por vida','Lifetime license active; online verification refresh pending':'Licencia activa de por vida; renovando la comprobación online','Cloud unlock active':'Licencia confirmada online','Cloud license active':'Licencia confirmada online','Offline license active; no license server configured':'Licencia local activa','Cloud unlock expired; grace period active':'Licencia activa de por vida','Could not validate the license online. Check internet access or contact support.':'No pudimos confirmar tu licencia. Revisa internet o contacta soporte.','License server unavailable; using the saved unlock on this device':'No pudimos contactar el servidor; tu licencia de por vida sigue activa en este equipo','Demo/internal license':'Licencia de prueba','Missing META_AD_ACCOUNT_ID':'Falta elegir cuenta publicitaria','Not configured; paste your Meta key in onboarding.':'Falta pegar tu clave de Meta en la configuración inicial.','Not configured; optional unless using graph_api connector.':'No configurado; normalmente puedes seguir.','Missing creative.destination.page_id':'Falta elegir página de Facebook','Missing creative.destination.url':'Falta guardar el link de tu web','Falta conectar ChatGPT/Codex para imágenes':'Falta conectar el generador de imágenes','Missing MINIMAX_API_KEY; chat will use local fallback replies.':'Plan B de chat no configurado. El agente sigue siendo el principal.','Set MINIMAX_API_KEY in .env for real agent conversation.':'Solo necesario si cambias el chat a MiniMax.','No creative drafts yet.':'Todavía no hay ideas de anuncios.','No upload payloads staged yet.':'Todavía no hay anuncios preparados para publicar.','None':'Ninguno','logs directory not created yet':'Todavía no hay carpeta de registros'
};
function t(key){return (copy[lang]&&copy[lang][key])||copy.en[key]||key}
function uiLang(){
 const selected=qs('#language-select')?.value;
 if(selected==='es'||selected==='en')return selected;
 const stored=localStorage.getItem('dashboardLang');
 if(stored==='es'||stored==='en')return stored;
 return lang==='en'?'en':'es';
}
function isEs(){return uiLang()==='es'}
function localText(value){if(lang!=='es')return value;let text=String(value??'');return esText[text]||text.replace(/^Missing: /,'Falta: ').replace('blocked / missing','bloqueado / faltan').replace('ready_for_approval','listo para aprobación').replace('dry-run','con aprobación').replace('True','Sí').replace('False','No')}
function actionName(value){const raw=String(value||'').replaceAll('_',' ');if(lang!=='es')return raw;return raw.replace('budget change','cambio de presupuesto').replace('resume campaign','reactivar campaña').replace('create campaign','crear campaña').replace('creative upload','subida creativa').replace('daily agent run','ejecución diaria del agente').replace('creative refresh','renovación creativa').replace('creative upload execute','ejecución de subida creativa').replace('creative upload stage','preparación de subida creativa')}
function actionDetail(a){const p=a.payload||{};const result=p.result||p.graph_result||{};const requested=p.name||p.campaign_name||p.campaign_id||p.path||'';const connector=p.connector||result.connector||(result.graph_endpoint||result.command?'graph_api':'local');const mode=p.mode||result.mode||state?.config?.mode||'';const executed=(p.executed!==undefined?p.executed:result.executed);const response=result.stderr||result.stdout||p.response_summary||'';const rows=[];if(requested)rows.push(`<strong>${lang==='es'?'Pedido':'Requested'}:</strong> ${requested}`);rows.push(`<strong>${lang==='es'?'Conector':'Connector'}:</strong> ${connector}`);if(mode)rows.push(`<strong>${lang==='es'?'Modo':'Mode'}:</strong> ${mode}`);if(executed!==undefined)rows.push(`<strong>${lang==='es'?'Ejecutado':'Executed'}:</strong> ${executed? (lang==='es'?'sí':'yes') : (lang==='es'?'no':'no')}`);if(response)rows.push(`<strong>${lang==='es'?'Respuesta':'Response'}:</strong> ${String(response).slice(0,180)}`);return rows.length?`<div class="action-detail">${rows.join('<br>')}</div>`:''}
function keyFor(label){return labelKeys[label]||label}
function tip(label){const key=keyFor(label);return `<span class="tip" tabindex="0" data-tip="${t(key+'_tip')}">${t(key)} <span class="help-dot">?</span></span>`}
function kpi(label,value){return `<div class="kpi aurora-card"><span class="starfield" aria-hidden="true"></span><div class="v">${value}</div><div class="l">${tip(label)}</div></div>`}
function metric(label,value){return `<div class="metric"><b>${value}</b><span>${tip(label)}</span></div>`}
function priorityMetricLabel(row){return String((lang==='es'?row?.label_es:row?.label)||row?.label_es||row?.label||row?.key||'')}
function priorityMetricValue(row){if(!row||row.available===false||row.value===null||row.value===undefined)return '—';const value=Number(row.value||0);if(row.format==='currency')return fmtMoney(value);if(row.format==='ratio')return value.toFixed(2)+'x';if(row.format==='percent')return fmtPct(value);if(row.format==='decimal')return value.toFixed(2);return value.toLocaleString(lang==='es'?'es-CO':'en-US',{maximumFractionDigits:2})}
function priorityMetric(row){return `<div class="metric adaptive-metric"><b>${escapeHtml(priorityMetricValue(row))}</b><span>${escapeHtml(priorityMetricLabel(row))}</span></div>`}
function priorityKpi(row){return `<div class="kpi aurora-card adaptive-kpi"><span class="starfield" aria-hidden="true"></span><div class="v">${escapeHtml(priorityMetricValue(row))}</div><div class="l">${escapeHtml(priorityMetricLabel(row))}</div></div>`}
function campaignPriorityRows(campaign){const rows=Array.isArray(campaign?.priority_metrics)?campaign.priority_metrics.filter(Boolean):[];if(rows.length)return rows.slice(0,6);return [{key:'spend',label:'Spend',label_es:'Gasto',format:'currency',value:campaign?.spend,available:true},{key:'results',label:'Results',label_es:'Resultados',format:'number',value:campaign?.conversions,available:true},{key:'ctr',label:'CTR',label_es:'CTR',format:'percent',value:campaign?.ctr,available:true},{key:'frequency',label:'Frequency',label_es:'Frecuencia',format:'decimal',value:campaign?.frequency,available:true}]}
function campaignMetricSnapshot(campaign){return campaignPriorityRows(campaign).slice(0,4).map(row=>`${priorityMetricLabel(row)} ${priorityMetricValue(row)}`).join(' · ')}
function adaptiveReportCell(campaign,index){const row=campaignPriorityRows(campaign)[index];return row?`<span class="report-metric"><b>${escapeHtml(priorityMetricValue(row))}</b><small>${escapeHtml(priorityMetricLabel(row))}</small></span>`:'—'}
function explainTerms(text){return String(text||'').replace(/\b(ROAS|CPA|CTR|CPC|Frequency|frequency|conversions|Conversions|Active daily budget|active daily budget|daily budget)\b/g,match=>tip(match))}
function briefAnswer(text){
 if(lang!=='es')return text;
 let answer=String(text||'')
  .replace(/^Spend:\s*/,'Gasto: ')
  .replace(/^Revenue:\s*/,'Ingresos: ')
  .replace(/^(\d+) active campaigns\.?$/,'$1 campañas activas.')
  .replace(/^(\d+) fatigue flag\(s\)\.?$/,'$1 señales de cansancio del anuncio.')
  .replace(/^Active daily budget is /,'El presupuesto diario activo es ')
  .replace('; account ROAS is ','; el ROAS de la cuenta es ')
  .replace(' with CPA ',' con CPA ')
  .replace(/^(\d+) active campaigns, (\d+) paused or staged\.$/,'$1 campañas activas, $2 pausadas o preparadas.')
  .replace(/^7-day view shows /,'Vista de 7 días: ')
  .replace(' spend, ',' de gasto, ')
  .replace(' revenue, ',' de ingresos, ')
  .replace(' conversions, and ',' conversiones y ')
  .replace(/^Top winner: /,'Mejor campaña: ')
  .replace(' at ',' con ')
  .replace('No material fatigue triggers right now.','No hay señales importantes de cansancio por ahora.')
  .replace('No clear winner yet.','Todavía no hay una campaña claramente ganadora.');
 if(state?.metrics?.source==='demo'){
  answer=answer.replaceAll('Q2 Conversion Campaign','Campaña de ventas Q2')
   .replaceAll('Brand Awareness Campaign','Campaña para dar a conocer la marca')
   .replaceAll('Retargeting - Warm Leads','Personas que ya mostraron interés')
   .replaceAll('Prospecting - Broad Testing','Prueba con personas nuevas');
 }
 return answer;
}
function recommendationText(text){
 if(lang!=='es')return text;
 const map={
  'High performance detected - increasing budget':'Buen rendimiento: conviene aumentar el presupuesto con cuidado.',
  'Good performance - maintaining current budget':'Buen rendimiento: conviene mantener el presupuesto actual.',
  'Average performance - slight budget reduction':'Rendimiento medio: conviene bajar un poco el presupuesto.',
  'Low performance - reducing budget significantly':'Rendimiento bajo: conviene reducir el presupuesto.',
  'Even distribution maintains stable performance':'Mantener este presupuesto ayuda a conservar estabilidad.'
 };
 return map[String(text||'')]||String(text||'')
  .replace('Highly efficient conversions - increasing budget aggressively','Compras a buen costo: conviene aumentar el presupuesto con cuidado.')
  .replace('Efficient conversions - increasing budget moderately','Compras a buen costo: conviene aumentar un poco el presupuesto.')
  .replace('Break-even efficiency - maintaining budget','Resultados estables: conviene mantener el presupuesto.')
  .replace('Inefficient conversions - decreasing budget','Compras costosas: conviene bajar el presupuesto.');
}
function fatigueText(text){
 if(lang!=='es')return text;
 return String(text||'')
  .replace(/^frequency ([\d.]+)$/,'Una persona lo ve $1 veces')
  .replace(/^CTR ([\d.]+)% down$/,'Los clics bajaron $1%')
  .replace(/^CPC ([\d.]+)% up$/,'Cada clic cuesta $1% más');
}
function demoCampaignName(name){
 if(lang!=='es'||state?.metrics?.source!=='demo')return name;
 const map={'Q2 Conversion Campaign':'Campaña de ventas Q2','Brand Awareness Campaign':'Campaña para dar a conocer la marca','Retargeting - Warm Leads':'Personas que ya mostraron interés','Prospecting - Broad Testing':'Prueba con personas nuevas'};
 return map[name]||name;
}
function briefQuestion(q){return t(questionKeys[q]||q)}
function modeText(value){return lang==='es'?'aprobación':'approval'}
function statusText(value){const map={active:lang==='es'?'activa':'active',paused:lang==='es'?'pausada':'paused',winning:lang==='es'?'ganadora':'winning',losing:lang==='es'?'perdedora':'losing',fatigue:lang==='es'?'cansancio':'fatigue',neutral:lang==='es'?'neutral':'neutral',blocked:lang==='es'?'bloqueado':'blocked',warn:lang==='es'?'alerta':'warn',ok:lang==='es'?'ok':'ok'};return map[value]||value}
function applyTranslations(){
 document.documentElement.lang=lang;
 qs('#language-select').value=lang;
 document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
 document.querySelectorAll('[data-i18n-placeholder]').forEach(el=>{el.placeholder=t(el.dataset.i18nPlaceholder)});
 qs('#top-roas').innerHTML=tip('ROAS'); qs('#top-cpa').innerHTML=tip('CPA'); qs('#top-mode').innerHTML=tip('Mode');
 qs('#th-spend').textContent=lang==='es'?'Prioridad 1':'Priority 1'; qs('#th-roas').textContent=lang==='es'?'Prioridad 2':'Priority 2'; qs('#th-cpa').textContent=lang==='es'?'Prioridad 3':'Priority 3'; qs('#th-ctr').textContent=lang==='es'?'Prioridad 4':'Priority 4';
 applyDashboardTheme();
 syncDashboardView();
 syncPanels();
}
function setDashboardBooting(active){
 const title=qs('#dashboard-boot-title'),detail=qs('#dashboard-boot-detail');
 if(title)title.textContent=lang==='es'?'Preparando tu dashboard':'Preparing your dashboard';
 if(detail)detail.textContent=lang==='es'?'Cargando tus datos guardados…':'Loading your saved data…';
 document.body.classList.toggle('dashboard-booting',Boolean(active));
 document.body.setAttribute('aria-busy',active?'true':'false');
}
function viewLabels(){return lang==='es'?{control:'Control',timeline:'En el tiempo',analytics:'Vista total',idle:'Producto',aurora:'Aurora',sapphire:'Sapphire',ember:'Ember'}:{control:'Control',timeline:'Timeline',analytics:'Total view',idle:'Showcase',aurora:'Aurora',sapphire:'Sapphire',ember:'Ember'}}
function applyDashboardTheme(){
 dashboardTheme=normalizeDashboardTheme(dashboardTheme);
 document.body.classList.toggle('theme-aurora',dashboardTheme==='aurora');
 document.body.classList.toggle('theme-sapphire',dashboardTheme==='sapphire');
 document.body.classList.toggle('theme-ember',dashboardTheme==='ember');
 document.body.classList.toggle('theme-light',dashboardTheme==='aurora');
 document.body.classList.toggle('theme-dark',dashboardTheme==='sapphire'||dashboardTheme==='ember');
 const labels=viewLabels();
 document.querySelectorAll('.theme-chip').forEach(btn=>{const theme=normalizeDashboardTheme(btn.dataset.theme);btn.textContent=labels[theme]||theme;btn.classList.toggle('active',theme===dashboardTheme);btn.setAttribute('aria-pressed',theme===dashboardTheme?'true':'false')});
 const group=qs('#theme-toggle');if(group)group.setAttribute('aria-label',lang==='es'?'Temas del dashboard':'Dashboard themes');
}
function setDashboardTheme(theme){dashboardTheme=normalizeDashboardTheme(theme);localStorage.setItem('dashboardTheme',dashboardTheme);applyDashboardTheme()}
function toggleDashboardTheme(){setDashboardTheme(dashboardTheme==='aurora'?'sapphire':dashboardTheme==='sapphire'?'ember':'aurora')}
function syncDashboardView(){
 const labels=viewLabels();
 document.querySelectorAll('.view-chip').forEach(btn=>{const view=btn.dataset.view;btn.textContent=labels[view]||view;btn.classList.toggle('active',view===dashboardView);btn.setAttribute('aria-pressed',view===dashboardView?'true':'false')});
 ['control','timeline','analytics','idle'].forEach(view=>{const el=qs(`#view-${view}`);if(el)el.classList.toggle('hidden',view!==dashboardView)})
}
function setDashboardView(view){dashboardView=view;localStorage.setItem('dashboardView',view);syncDashboardView();renderOverviewViews()}
function positionFloatingTip(target){
 const box=qs('#floating-tip'); if(!box||!target)return;
 box.textContent=target.dataset.tip||''; box.classList.add('show');
 const rect=target.getBoundingClientRect(); const tipRect=box.getBoundingClientRect(); const gap=10; const margin=12;
 let left=rect.left+(rect.width-tipRect.width)/2;
 left=Math.max(margin,Math.min(left,window.innerWidth-tipRect.width-margin));
 let top=rect.top-tipRect.height-gap;
 if(top<margin)top=rect.bottom+gap;
 if(top+tipRect.height>window.innerHeight-margin)top=Math.max(margin,window.innerHeight-tipRect.height-margin);
 box.style.left=`${left}px`; box.style.top=`${top}px`;
}
function hideFloatingTip(){const box=qs('#floating-tip');if(box)box.classList.remove('show')}
document.addEventListener('pointerover',e=>{const target=e.target.closest?.('.tip');if(target)positionFloatingTip(target)})
document.addEventListener('pointerout',e=>{const target=e.target.closest?.('.tip');if(target&&!target.contains(e.relatedTarget))hideFloatingTip()})
document.addEventListener('focusin',e=>{const target=e.target.closest?.('.tip');if(target)positionFloatingTip(target)})
document.addEventListener('focusout',e=>{if(e.target.closest?.('.tip'))hideFloatingTip()})
document.addEventListener('scroll',hideFloatingTip,true)
window.addEventListener('resize',()=>{hideFloatingTip();syncPanels()})
function toast(msg){const t=qs('#toast');t.textContent=msg;t.style.display='block';setTimeout(()=>t.style.display='none',2600)}
function fillTemplate(text){const s=state?.metrics?.summary||{};return String(text).replace('{roas}',Number(s.overall_roas||0).toFixed(2)).replace('{cpa}',fmtMoney(s.overall_cpa)).replace('{budget}',fmtMoney(s.active_budget)).replace('{pending}',state?.pending?.length||0)}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function isMobilePanelLayout(){return window.matchMedia('(max-width: 780px)').matches}
function panelStorageKey(side){const desktopKey=`dashboardPanel:${side}`;return isMobilePanelLayout()?`dashboardPanelMobile:${side}`:desktopKey}
function panelOpen(side){return localStorage.getItem(panelStorageKey(side))==='open'}
let dailyBriefReadTimer=null;
function dailyBriefStamp(){return String(state?.brief?.generated_at||state?.metrics?.timestamp||'')}
function hasUnreadDailyBrief(){const stamp=dailyBriefStamp();return Boolean(stamp&&state?.brief?.questions?.length&&localStorage.getItem('dashboardDailyBriefReadStamp')!==stamp)}
function syncDailyBriefUnread(){
 const unread=hasUnreadDailyBrief();
 const btn=qs('#toggle-left-panel');if(!btn)return;
 btn.classList.toggle('has-new-brief',unread);
 btn.setAttribute('data-unread',unread?'true':'false');
 const badge=qs('#daily-brief-badge');if(badge){badge.textContent=t('new_brief');badge.setAttribute('aria-hidden',unread?'false':'true')}
}
function markDailyBriefRead(){const stamp=dailyBriefStamp();if(stamp)localStorage.setItem('dashboardDailyBriefReadStamp',stamp);syncDailyBriefUnread()}
function scheduleVisibleBriefRead(){
 clearTimeout(dailyBriefReadTimer);
 if(!panelOpen('left')||!hasUnreadDailyBrief())return;
 const stamp=dailyBriefStamp();
 dailyBriefReadTimer=setTimeout(()=>{if(panelOpen('left')&&dailyBriefStamp()===stamp)markDailyBriefRead()},2200);
}
function panelTitle(side,open){
 if(side==='left')return open?(lang==='es'?'Ocultar perfil y lectura':'Hide profile and daily read'):(lang==='es'?'Mostrar perfil y lectura':'Show profile and daily read');
 return open?(lang==='es'?'Ocultar aprobaciones y actividad':'Hide approvals and activity'):(lang==='es'?'Mostrar aprobaciones y actividad':'Show approvals and activity')
}
function syncPanels(){
 const left=panelOpen('left'),right=panelOpen('right');
 document.body.classList.toggle('left-panel-open',left);
 document.body.classList.toggle('right-panel-open',right);
 [['left',left],['right',right]].forEach(([side,open])=>{
  const btn=qs(`#toggle-${side}-panel`);if(!btn)return;
  const title=panelTitle(side,open);
  btn.classList.toggle('active',open);btn.setAttribute('aria-expanded',open?'true':'false');btn.setAttribute('aria-label',title);btn.title=title;
 })
 syncDailyBriefUnread();
 scheduleVisibleBriefRead();
}
function togglePanel(side){const open=panelOpen(side);localStorage.setItem(panelStorageKey(side),open?'closed':'open');syncPanels();if(side==='left')markDailyBriefRead()}
function inlineMarkdown(value){return escapeHtml(value).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')}
function formatChatContent(text){
 const raw=fillTemplate(text).replace(/\r\n/g,'\n').trim();
 if(!raw)return '';
 const blocks=[]; let list=[];
 const flushList=()=>{if(list.length){blocks.push(`<ul>${list.map(item=>`<li>${inlineMarkdown(item)}</li>`).join('')}</ul>`);list=[]}};
 raw.split(/\n+/).forEach(line=>{
  const trimmed=line.trim();
  if(!trimmed)return flushList();
  const bullet=trimmed.match(/^[-*]\s+(.+)$/);
  const numbered=trimmed.match(/^\d+[.)]\s+(.+)$/);
  if(bullet||numbered){list.push((bullet||numbered)[1]);return}
  flushList();
  blocks.push(`<p>${inlineMarkdown(trimmed)}</p>`);
 });
 flushList();
 return blocks.join('');
}
function buyerSafeChatContent(value){let text=String(value??'');text=text.replace(/\b(?:aprueba|aprobar)\s+approval_[A-Za-z0-9_-]+\b/gi,'responde “aprobado”');text=text.replace(/\bapprove\s+approval_[A-Za-z0-9_-]+\b/gi,'reply “approved”');text=text.replace(/\bapproval_[A-Za-z0-9_-]+\b/g,'').replace(/[ \t]{2,}/g,' ');return text}
function setMessageContent(node,text){const raw=fillTemplate(text);const content=node.classList.contains('agent')?buyerSafeChatContent(raw):raw;node.classList.remove('thinking');node.innerHTML=formatChatContent(content);node.dataset.rawContent=content;return content}
function addMessage(role,text,store=true){const log=qs('#chat-log');const node=document.createElement('div');node.className=`msg ${role}`;const content=setMessageContent(node,text);log.appendChild(node);log.scrollTop=log.scrollHeight;if(store)chatHistory.push({role,content});return node}
function chatApprovalItems(result){
 const routed=result?.routed_action||{};const items=[];
 if(Array.isArray(result?.approval_choices))items.push(...result.approval_choices);
 if(Array.isArray(routed?.approval_choices))items.push(...routed.approval_choices);
 const candidate=routed?.result;
 if(candidate&&candidate.id&&candidate.status==='pending')items.push(candidate);
 const seen=new Set();
 return items.filter(item=>{const id=item&&item.id;if(!id||seen.has(id))return false;seen.add(id);return true}).slice(0,4);
}
function approvalItemName(item){return escapeHtml(item.name||item.payload?.name||item.payload?.campaign_name||item.type||'Decisión pendiente')}
function appendChatApprovalActions(node,result){
 const items=chatApprovalItems(result);if(!items.length)return;
 const wrap=document.createElement('div');wrap.className='msg-actions approval-chat-actions';
 wrap.innerHTML=items.map(item=>{const active=item.requires_active_confirmation||item.type==='resume_campaign'||item.type==='activate_campaign'||item.final_status==='ACTIVE'||item.payload?.final_status==='ACTIVE';const approveLabel=active?(lang==='es'?'Sí, activar':'Yes, activate'):(lang==='es'?'Aprobar':'Approve');return `<div class="msg-approval-card"><b>${approvalItemName(item)}</b><span>${escapeHtml(item.type||'approval')}</span><div class="msg-approval-buttons"><button class="btn primary" type="button" data-action-code="chatApproveDecision('${escapeHtml(item.id)}')">${approveLabel}</button><button class="btn danger" type="button" data-action-code="chatRejectDecision('${escapeHtml(item.id)}')">${lang==='es'?'No aprobar':'Reject'}</button></div></div>`}).join('');
 node.appendChild(wrap);qs('#chat-log').scrollTop=qs('#chat-log').scrollHeight;
}
async function chatApproveDecision(id){const attempted=await approvePending(id);const done=Array.isArray(attempted)&&attempted[0]?.status==='approved';addMessage('agent',done?(lang==='es'?'Listo. Aprobé y ejecuté esa decisión.':'Done. I approved and executed that decision.'):(lang==='es'?'Intenté aprobarla, pero quedó pendiente para reintentar. Revisa el detalle en Aprobaciones.':'I tried to approve it, but it remains pending for retry. Check the detail in Approvals.'))}
async function chatRejectDecision(id){await api('/api/reject',{method:'POST',body:JSON.stringify({approval_id:id,reason:'Rejected from chat button'})});toast(lang==='es'?'Decisión rechazada':'Decision rejected');await load();addMessage('agent',lang==='es'?'Listo. Rechacé esa decisión y no se ejecutará.':'Done. I rejected that decision and it will not execute.')}
function hydrateChatHistory(force=false){
 if(chatHydrated&&!force)return;
 const log=qs('#chat-log');if(!log)return;
 const history=Array.isArray(state?.chat_history)?state.chat_history:[];
 log.innerHTML='';chatHistory=[];
 history.slice(-40).forEach(item=>addMessage(item.role==='agent'?'agent':'user',item.content,false));
 chatHistory=history.slice(-40).map(item=>({role:item.role==='agent'?'agent':'user',content:item.content}));
 chatHydrated=true;
}
function streamMessageContent(node,text){
 const raw=fillTemplate(text);
 const content=node.classList.contains('agent')?buyerSafeChatContent(raw):raw;
 node.dataset.rawContent='';
 node.classList.remove('thinking');
 node.classList.add('streaming');
 const parts=content.match(/\S+\s*/g)||[''];
 let index=0;
 return new Promise(resolve=>{
  const tick=()=>{
   index+=1;
   const partial=parts.slice(0,index).join('');
   node.dataset.rawContent=partial;
   node.innerHTML=formatChatContent(partial);
   qs('#chat-log').scrollTop=qs('#chat-log').scrollHeight;
   if(index<parts.length){setTimeout(tick,18)}else{node.classList.remove('streaming');resolve(content)}
  };
  tick();
 });
}
function openChat(draft=''){hydrateChatHistory();document.body.classList.add('chat-workspace-open');const panel=qs('#chat-panel');panel.classList.add('open');if(!qs('#chat-log').children.length)addMessage('agent',t('chat_welcome'));if(draft)qs('#chat-input').value=draft;resizeChatInput();qs('#chat-input').focus()}
function closeChat(){qs('#chat-panel').classList.remove('open');document.body.classList.remove('chat-workspace-open')}
function resizeChatInput(){const input=qs('#chat-input');if(!input)return;input.style.height='auto';const max=150;const next=Math.min(input.scrollHeight,max);input.style.height=`${next}px`;input.style.overflowY=input.scrollHeight>max?'auto':'hidden'}
function resizeAgentBarInput(){const input=qs('#agent-bar-input');if(!input)return;input.style.height='auto';const max=92;const next=Math.min(input.scrollHeight,max);input.style.height=`${next}px`;input.style.overflowY=input.scrollHeight>max?'auto':'hidden'}
async function sendChatMessage(text,{workspace=false,memoryWizard=null}={}){
 if(!text)return;
 if(workspace)document.body.classList.add('chat-workspace-open');
 openChat();
 addMessage('user',text);
 const pending=addMessage('agent',lang==='es'?'Pensando...':'Thinking...',false);pending.classList.add('thinking');
 try{const chatPayload={message:text,history:chatHistory,metrics:state.metrics,recommendations:state.recommendations,fatigue:state.fatigue,pending:state.pending,language:lang};if(memoryWizard)chatPayload.memory_wizard=memoryWizard;const res=await api('/api/chat',{method:'POST',body:JSON.stringify(chatPayload)});const reply=res.result.reply||agentReply(text);const rendered=await streamMessageContent(pending,reply);chatHistory.push({role:'agent',content:rendered});appendChatApprovalActions(pending,res.result);if(res.result.routed_action){await load();const action=res.result.routed_action;if(action.type==='creative_memory_wizard_complete'){toast(lang==='es'?'Información del anuncio actualizada':'Creative memory updated')}}}catch(err){const raw=String(err&&err.message||err||'');const needsPassword=raw.includes('dashboard password')||raw.includes('password')||raw.includes('401');const fallback=needsPassword?(lang==='es'?'Necesito la contraseña del dashboard para hablar con el agente real y ejecutar acciones protegidas. Desbloquea el dashboard y vuelve a enviar el mensaje.':'I need the dashboard password to talk to the real agent and run protected actions. Unlock the dashboard and send the message again.'):agentReply(text);const rendered=await streamMessageContent(pending,fallback);chatHistory.push({role:'agent',content:rendered})}
}
async function newChatConversation(){
 await api('/api/chat/reset',{method:'POST',body:JSON.stringify({})});
 chatHistory=[];chatHydrated=true;qs('#chat-log').innerHTML='';addMessage('agent',t('chat_welcome'));
 toast(lang==='es'?'Conversación nueva lista':'New conversation ready');
}
function agentReply(text){const msg=String(text||'').toLowerCase();if(msg.includes('presupuesto')||msg.includes('budget'))return t('chat_budget');if(msg.includes('fatiga')||msg.includes('creative')||msg.includes('creativo'))return t('chat_fatigue');if(msg.includes('config')||msg.includes('setup')||msg.includes('live'))return t('chat_setup');if(msg.includes('resumen')||msg.includes('catch')||msg.includes('dónde')||msg.includes('where'))return t('chat_summary');return `${t('chat_summary')}\n\n${t('chat_action_hint')}`}
function normalizeClientMetricsRange(value){const range=value&&typeof value==='object'?value:{};const preset=['maximum','today','last_7d','custom'].includes(range.preset)?range.preset:'maximum';return {preset,since:String(range.since||''),until:String(range.until||'')}}
function localDateValue(value=new Date()){const date=value instanceof Date?value:new Date(value);const offset=date.getTimezoneOffset()*60000;return new Date(date.getTime()-offset).toISOString().slice(0,10)}
function metricsRangeText(range=metricsRange){const value=normalizeClientMetricsRange(range);if(value.preset==='today')return lang==='es'?'Hoy':'Today';if(value.preset==='last_7d')return lang==='es'?'Últimos 7 días':'Last 7 days';if(value.preset==='custom'){const display=date=>{if(!date)return '--';const parsed=new Date(`${date}T12:00:00`);return parsed.toLocaleDateString(lang==='es'?'es-CO':'en-US',{day:'numeric',month:'short',year:'numeric'})};return `${display(value.since)} – ${display(value.until)}`}return lang==='es'?'Desde siempre':'All time'}
function renderMetricsRange(){const label=qs('#metrics-range-label');if(label)label.textContent=metricsRangeText();const title=qs('#metrics-range-title');if(title)title.textContent=lang==='es'?'Período de métricas':'Metrics period';document.querySelectorAll('.metrics-range-chip').forEach(button=>{const active=button.dataset.range===metricsRange.preset;button.classList.toggle('active',active);button.setAttribute('aria-pressed',active?'true':'false')});const names={maximum:lang==='es'?'Desde siempre':'All time',today:lang==='es'?'Hoy':'Today',last_7d:lang==='es'?'Últimos 7 días':'Last 7 days',custom:lang==='es'?'Personalizado':'Custom'};Object.entries(names).forEach(([key,text])=>{const button=qs(`#metrics-range-${key.replaceAll('_','-')}`);if(button)button.textContent=text});const custom=qs('#metrics-custom-range');if(custom)custom.classList.toggle('hidden',!metricsCustomOpen);const today=localDateValue();const since=qs('#metrics-range-since');const until=qs('#metrics-range-until');if(since){since.max=today;if(!since.value)since.value=metricsRange.preset==='custom'&&metricsRange.since?metricsRange.since:localDateValue(new Date(Date.now()-29*86400000))}if(until){until.max=today;if(!until.value)until.value=metricsRange.preset==='custom'&&metricsRange.until?metricsRange.until:today}if(custom){const spans=custom.querySelectorAll('label span');if(spans[0])spans[0].textContent=lang==='es'?'Desde':'From';if(spans[1])spans[1].textContent=lang==='es'?'Hasta':'To';const button=custom.querySelector('button');if(button)button.textContent=lang==='es'?'Aplicar':'Apply'}}
async function setMetricsRange(preset){metricsRange=normalizeClientMetricsRange({preset});metricsRangeTouched=true;metricsCustomOpen=false;renderMetricsRange();await refreshInsights({scope:'full',range:metricsRange})}
function openCustomMetricsRange(){metricsCustomOpen=true;renderMetricsRange();setTimeout(()=>qs('#metrics-range-since')?.focus(),20)}
async function applyCustomMetricsRange(event){event?.preventDefault();const since=String(qs('#metrics-range-since')?.value||'');const until=String(qs('#metrics-range-until')?.value||'');if(!since||!until){toast(lang==='es'?'Elige las dos fechas.':'Choose both dates.');return}if(since>until){toast(lang==='es'?'La fecha inicial no puede ser posterior a la final.':'The start date cannot be after the end date.');return}metricsRange={preset:'custom',since,until};metricsRangeTouched=true;metricsCustomOpen=false;renderMetricsRange();await refreshInsights({scope:'full',range:metricsRange})}
function dataSourceText(m){const source=String(m?.source||'');const period=metricsRangeText(m?.metrics_range||metricsRange);if(source==='meta_graph')return lang==='es'?`Meta en vivo · ${period} · cada 2 min`:`Live Meta · ${period} · every 2 min`;if(source==='demo')return lang==='es'?'Datos de ejemplo, no reales':'Demo data, not real';if(source==='missing')return lang==='es'?'Sin datos reales de Meta':'No real Meta data yet';return lang==='es'?'Datos guardados sin confirmar':'Saved unverified data'}
function chatArg(value){return JSON.stringify(String(value||'')).replaceAll('"','&quot;')}
function splitActionStatements(code){
 const out=[];let current='',quote='',depth=0,escaped=false;
 for(const ch of String(code||'')){
  if(quote){current+=ch;if(escaped){escaped=false;continue}if(ch==='\\'){escaped=true;continue}if(ch===quote)quote='';continue}
  if(ch==="'"||ch==='"'||ch==='`'){quote=ch;current+=ch;continue}
  if(ch==='('||ch==='['||ch==='{')depth+=1;
  if(ch===')'||ch===']'||ch==='}')depth=Math.max(0,depth-1);
  if(ch===';'&&depth===0){if(current.trim())out.push(current.trim());current='';continue}
  current+=ch;
 }
 if(current.trim())out.push(current.trim());
 return out;
}
function splitActionArgs(text){
 const out=[];let current='',quote='',depth=0,escaped=false;
 for(const ch of String(text||'')){
  if(quote){current+=ch;if(escaped){escaped=false;continue}if(ch==='\\'){escaped=true;continue}if(ch===quote)quote='';continue}
  if(ch==="'"||ch==='"'||ch==='`'){quote=ch;current+=ch;continue}
  if(ch==='('||ch==='['||ch==='{')depth+=1;
  if(ch===')'||ch===']'||ch==='}')depth=Math.max(0,depth-1);
  if(ch===','&&depth===0){out.push(current.trim());current='';continue}
  current+=ch;
 }
 if(current.trim())out.push(current.trim());
 return out;
}
function unquoteActionValue(expr){
 const raw=String(expr||'').trim();
 if((raw.startsWith("'")&&raw.endsWith("'"))||(raw.startsWith('"')&&raw.endsWith('"'))||(raw.startsWith('`')&&raw.endsWith('`'))){
  try{return JSON.parse(raw[0]==="'"?`"${raw.slice(1,-1).replace(/\\/g,'\\\\').replace(/"/g,'\\"')}"`:raw)}
  catch(_){return raw.slice(1,-1)}
 }
 return raw;
}
function evalActionExpression(expr,event,source){
 const raw=String(expr||'').trim();
 if(raw==='event')return event;
 if(raw==='source')return source;
 if(raw==='true')return true;
 if(raw==='false')return false;
 if(raw==='null')return null;
 if(raw==='undefined')return undefined;
 if(raw==='lang')return lang;
 if(raw==='window.pendingLicenseActivationPayload||{}')return window.pendingLicenseActivationPayload||{};
 if(raw==="qs('#onboarding-flow')?.classList.contains('open')")return Boolean(qs('#onboarding-flow')?.classList.contains('open'));
 if(raw==='onboardingFlowStep')return onboardingFlowStep;
 let stepDelta=raw.match(/^onboardingFlowStep([+-])(\d+)$/);
 if(stepDelta)return onboardingFlowStep+(stepDelta[1]==='-'?-1:1)*Number(stepDelta[2]);
 if(/^[-+]?\d+(\.\d+)?$/.test(raw))return Number(raw);
 let m=raw.match(/^t\((['"])(.*?)\1\)$/);if(m)return t(m[2]);
 if(raw==='businessProfileChatPrompt()')return businessProfileChatPrompt();
 m=raw.match(/^isEs\(\)\?(['"`])([\s\S]*)\1:(['"`])([\s\S]*)\3$/);if(m)return isEs()?m[2]:m[4];
 m=raw.match(/^lang===['"]es['"]\?(['"`])([\s\S]*)\1:(['"`])([\s\S]*)\3$/);if(m)return lang==='es'?m[2]:m[4];
 if((raw.startsWith("'")&&raw.endsWith("'"))||(raw.startsWith('"')&&raw.endsWith('"'))||(raw.startsWith('`')&&raw.endsWith('`')))return unquoteActionValue(raw);
 if(raw.startsWith('[')||raw.startsWith('{')){try{return JSON.parse(raw)}catch(_){}}
 return raw;
}
function allowedActionCall(name){
 const actions={
  openUsageGuide,togglePanel,openChat,runAgent,setDashboardView,setDashboardTheme,refreshInsights,setMetricsRange,openCustomMetricsRange,applyCustomMetricsRange,load,setTargetingMode,searchTargeting,
  generateRefresh,exportCsv,closeBrandMemory,newChatConversation,closeChat,chatApproveDecision,chatRejectDecision,removeTargetingItem,
  addTargetingItem,startCreativeMemoryWizard,refreshForProduct,startAdBriefForProduct,chatForProduct,refreshForAdBrief,chatForAdBrief,
  openBrandMemory,clearCreativeStorage,stageUpload,downloadCreativeAsset,confirmClearCreativeStorage,approvePending,resetOnboarding,
  copyCommand,skipWebsiteScan,setBusinessContextQuestionIndex,setMetaGuideSlide,setMetaGuideFrame,openMetaScreenshot,closeConfirm,skipOnboarding,closeUsageGuide,finishDashboardIntroTour,
  previousDashboardIntroTour,nextDashboardIntroTour,setMode,activateLicense,openMetaSettingsGuide,testTelegram,applyRec,resumeOnboarding,
  completeOnboarding,connectMetaStarted,showMetaTokenBox,saveMetaToken,discoverMetaAssets,pollChatGptConnection,reopenChatGptAuthUrl,
  goToMetaTokenStep,refreshSocialAccounts,selectTelegramChat,autoSaveTelegramToken,autoSaveTelegramSetting,selectSocialAccount,selectSocialAccountFromElement,selectMetaDestination,resolveDecisionConfirm,
  finishOnboardingConfirmed,confirmBusinessReplacement,confirmMigrationRestore,confirmUpdateRollback,rollbackUpdateSnapshot,
  applyDashboardUpdate,submitBudgetDialog,submitBrandGuideInit,saveOnboardingSetupConfig,saveTelegramConfig,saveCommunicationStyle,saveGeneralMemory,
  saveProductMemory,saveAdBriefMemory,uploadBrandLogo,activateLicenseFromForm,setDashboardPasswordFromOnboarding,saveBusinessLinks,
  saveBusinessContextQuestion,saveGuardrails,saveProfitabilityRules,saveOptimizationSettings,saveShopifyConfig,testShopifyConnection,syncShopifyOutcomes,unlockOptimization,saveSetupConfig,savePublishingConfig,testPublishingConnection,disconnectPublishingConfig,sendChatGptTerminalInput,restoreMigrationBackup,
  budgetPrompt,campaignAction,detectTelegramChats,setLocalNetworkAccess,showDetails,selectAgentModelRoute,selectCompactAgentProvider,syncCompactAgentBase,saveChatGptModel,schedulePublishingTokenAutoSave,
  connectChatGpt,connectImageChatGpt,disconnectAgentModel,saveImageChatGptRouting,toggleChatGptDeviceAuthHelp,downloadMigrationBackup,refreshCloudAccess,loadUpdateSnapshots,showUpdateDetails,checkForUpdates,
  openDailyBriefSchedule,closeDailyBriefSchedule,saveDailyBriefSchedule,renderOnboardingFlow,setOnboardingFlowStep
 };
 return actions[name]||null;
}
function actionStatementName(statement){
 const code=String(statement||'').trim();
 if(code==='onboardingFlowTouched=true'||code==='pendingMigrationFile=null')return code;
 if(code.startsWith('onboardingFlowStep='))return 'onboardingFlowStep';
 let m=code.match(/^qs\((['"])(.*?)\1\)\.value=(['"])([\s\S]*)\3$/);if(m)return 'setFieldValue';
 m=code.match(/^qs\((['"])(.*?)\1\)\.click\(\)$/);if(m)return 'clickElement';
 if(code==='setTimeout(scheduleMetaTokenAutoSave,0)')return 'scheduleMetaTokenAutoSave';
 m=code.match(/^([A-Za-z_$][\w$]*)\(([\s\S]*)\)$/);return m?m[1]:'unknown';
}
function sequenceAllowed(names){
 const same=(a,b)=>a.length===b.length&&a.every((item,index)=>item===b[index]);
 return [
  ['closeConfirm','openChat'],
  ['pendingMigrationFile=null','closeConfirm'],
  ['closeConfirm','activateLicense'],
  ['resolveDecisionConfirm','openChat'],
  ['onboardingFlowTouched=true','onboardingFlowStep','renderOnboardingFlow']
 ].some(seq=>same(names,seq));
}
function runActionStatement(statement,event,source){
 const code=String(statement||'').trim();
 if(!code)return;
 if(code==='onboardingFlowTouched=true'){onboardingFlowTouched=true;return}
 if(code==='pendingMigrationFile=null'){pendingMigrationFile=null;return}
 if(code==='onboardingFlowStep=Math.max(0,onboardingFlowStep-1)'){onboardingFlowStep=Math.max(0,onboardingFlowStep-1);return}
 if(code==='onboardingFlowStep=Math.min(onboardingSteps().length-1,onboardingFlowStep+1)'){onboardingFlowStep=Math.min(onboardingSteps().length-1,onboardingFlowStep+1);return}
 let m=code.match(/^onboardingFlowStep=Math\.min\((\d+),onboardingFlowStep\+1\)$/);if(m){onboardingFlowStep=Math.min(Number(m[1]),onboardingFlowStep+1);return}
 m=code.match(/^qs\((['"])(.*?)\1\)\.value=(['"])([\s\S]*)\3$/);if(m){const el=qs(m[2]);if(el)el.value=m[4];return}
 m=code.match(/^qs\((['"])(.*?)\1\)\.click\(\)$/);if(m){qs(m[2])?.click();return}
 if(code==='setTimeout(scheduleMetaTokenAutoSave,0)'){setTimeout(scheduleMetaTokenAutoSave,0);return}
 m=code.match(/^([A-Za-z_$][\w$]*)\(([\s\S]*)\)$/);
 if(!m){console.warn('Blocked unsupported dashboard action',code);return}
 const fn=allowedActionCall(m[1]);
 if(!fn){console.warn('Blocked unknown dashboard action',m[1]);return}
 const args=splitActionArgs(m[2]).map(arg=>evalActionExpression(arg,event,source));
 return fn(...args);
}
function runActionCode(code,event,source){
 const statements=splitActionStatements(code);
 if(statements.length>1&&!sequenceAllowed(statements.map(actionStatementName))){
  console.warn('Blocked unsupported dashboard action sequence',code);
  return Promise.resolve();
 }
 return statements.reduce((chain,statement)=>chain.then(()=>runActionStatement(statement,event,source)),Promise.resolve());
}
function allowedStyleValue(value){return /^[-+.,%#()\w\s]+$/.test(String(value||''))&&String(value||'').length<120}
function applyDataStyles(root=document){
 const scope=root.nodeType===1?root:document;
 const nodes=[];
 if(scope.matches?.('[data-style-code]'))nodes.push(scope);
 scope.querySelectorAll?.('[data-style-code]').forEach(el=>nodes.push(el));
 nodes.forEach(el=>{
  String(el.dataset.styleCode||'').split(';').map(x=>x.trim()).filter(Boolean).forEach(rule=>{
   const index=rule.indexOf(':');if(index<1)return;
   const prop=rule.slice(0,index).trim();const value=rule.slice(index+1).trim();
   if(!/^(background|display|height|left|top|width|margin|margin-top|font-size)$/i.test(prop))return;
   if(!allowedStyleValue(value))return;
   el.style.setProperty(prop,value);
  });
 });
}
function installDelegatedActions(){
 document.addEventListener('click',event=>{
  const target=event.target.closest?.('[data-action-code]');
  if(!target)return;
  event.preventDefault();
  runActionCode(target.dataset.actionCode,event,target).catch(err=>{console.error(err);toast(err.message||String(err))});
 });
 document.addEventListener('submit',event=>{
  const target=event.target.closest?.('[data-submit-code]');
  if(!target)return;
  event.preventDefault();
  runActionCode(target.dataset.submitCode,event,target).catch(err=>{console.error(err);toast(err.message||String(err))});
 });
 document.addEventListener('change',event=>{
  const target=event.target.closest?.('[data-change-code]');
  if(!target)return;
  runActionCode(target.dataset.changeCode,event,target).catch(err=>{console.error(err);toast(err.message||String(err))});
 });
 document.addEventListener('input',event=>{
  const target=event.target.closest?.('[data-input-code]');
  if(!target)return;
  runActionCode(target.dataset.inputCode,event,target).catch(err=>console.error(err));
 });
 document.addEventListener('paste',event=>{
  const target=event.target.closest?.('[data-paste-code]');
  if(!target)return;
  runActionCode(target.dataset.pasteCode,event,target).catch(err=>console.error(err));
 });
 const observer=new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>applyDataStyles(node))));
 observer.observe(document.body,{childList:true,subtree:true});
 applyDataStyles(document);
}
let targetingSelections={location:[],interest:[]};
let targetingSearchResults={location:[],interest:[]};
function targetingDom(kind){return {query:qs(`#targeting-${kind}-query`),results:qs(`#targeting-${kind}-results`),selected:qs(`#targeting-${kind}-selected`),hidden:qs(`#campaign-targeting-${kind==='location'?'locations':'interests'}-json`)}}
function targetingMetaLine(item){if(item.kind==='interest'){const path=Array.isArray(item.path)&&item.path.length?` · ${item.path.join(' › ')}`:'';const size=item.audience_size?` · ${Number(item.audience_size).toLocaleString()}`:'';return `${path}${size}`.replace(/^ · /,'')}return [item.type,item.country_code].filter(Boolean).join(' · ')}
function syncTargetingHidden(kind){const dom=targetingDom(kind);if(dom.hidden)dom.hidden.value=JSON.stringify(targetingSelections[kind]||[])}
function renderSelectedTargeting(kind){const dom=targetingDom(kind);if(!dom.selected)return;const items=targetingSelections[kind]||[];dom.selected.innerHTML=items.map((item,index)=>`<span class="targeting-chip">${escapeHtml(item.label||item.name||item.key)} <button type="button" aria-label="${lang==='es'?'Quitar':'Remove'}" data-action-code="removeTargetingItem('${kind}',${index})">×</button></span>`).join('');syncTargetingHidden(kind)}
function addTargetingItem(kind,index){const item=(targetingSearchResults[kind]||[])[index];if(!item)return;const key=item.id||item.key||item.name;if(!(targetingSelections[kind]||[]).some(existing=>(existing.id||existing.key||existing.name)===key)){targetingSelections[kind].push(item)}renderSelectedTargeting(kind)}
function removeTargetingItem(kind,index){targetingSelections[kind].splice(index,1);renderSelectedTargeting(kind)}
function setTargetingMode(mode){document.querySelectorAll('.targeting-mode-card').forEach(btn=>btn.classList.remove('active'));const cards=[...document.querySelectorAll('.targeting-mode-card')];if(mode==='guided'&&cards[1])cards[1].classList.add('active');else if(mode==='warm'&&cards[2])cards[2].classList.add('active');else if(cards[0])cards[0].classList.add('active')}
async function searchTargeting(kind){
 const dom=targetingDom(kind);const q=(dom.query?.value||'').trim();
 if(!q){if(dom.results)dom.results.innerHTML=`<div class="targeting-empty">${t('targeting_need_query')}</div>`;return}
 if(dom.results)dom.results.innerHTML=`<div class="targeting-empty">${lang==='es'?'Buscando opciones reales de Meta...':'Searching real Meta options...'}</div>`;
 try{
  const res=await api('/api/targeting/search',{method:'POST',body:JSON.stringify({kind,q,limit:8})});
  const result=res.result||{};const items=result.items||[];targetingSearchResults[kind]=items;
  if(!result.ok){dom.results.innerHTML=`<div class="targeting-error">${escapeHtml(result.message||'Meta search unavailable')}</div>`;return}
  if(!items.length){dom.results.innerHTML=`<div class="targeting-empty">${t('targeting_no_results')}</div>`;return}
  dom.results.innerHTML=items.map((item,index)=>`<button class="targeting-result" type="button" data-action-code="addTargetingItem('${kind}',${index})"><span><b>${escapeHtml(item.label||item.name)}</b><span>${escapeHtml(targetingMetaLine(item))}</span></span><strong>+</strong></button>`).join('');
 }catch(err){if(dom.results)dom.results.innerHTML=`<div class="targeting-error">${escapeHtml(err.message||String(err))}</div>`}
}
function clamp(n,min,max){return Math.max(min,Math.min(max,n))}
function dayLabels(){return lang==='es'?['Lun','Mar','Mié','Jue','Vie','Sáb','Dom']:['Mon','Tue','Wed','Thu','Fri','Sat','Sun']}
function campaignInitials(name){return String(name||'AD').split(/\s+/).filter(Boolean).slice(0,2).map(x=>x[0]).join('').toUpperCase()||'AD'}
function aggregateTrend(campaigns){
 const rows=(campaigns||[]).filter(c=>Array.isArray(c.trend)&&c.trend.length);
 if(!rows.length)return [12,18,14,22,28,24,31];
 const len=Math.max(...rows.map(c=>c.trend.length));
 return Array.from({length:Math.min(7,len)},(_,i)=>rows.reduce((sum,c)=>sum+Number(c.trend[i%c.trend.length]||0),0));
}
function miniBars(values,cls=''){
 const max=Math.max(...values,1);
 return `<div class="mini-bars ${cls}">${values.map(v=>`<i data-style-code="height:${clamp((Number(v||0)/max)*64,10,70)}px"></i>`).join('')}</div>`;
}
function renderOverviewViews(){
 syncDashboardView();
 if(!state||!state.metrics)return;
 renderTimelineView();
 renderAnalyticsView();
 renderIdleView();
}
function renderTimelineView(){
 const box=qs('#view-timeline');if(!box)return;
 const campaigns=state.metrics?.campaigns||[];
 const days=dayLabels();
 const rows=campaigns.length?campaigns.map((c,i)=>{
  const left=clamp((i%4)*5,0,22);
  const width=c.status==='paused'?34:clamp(42+Number(c.roas||1)*6,42,82);
  const health=String(c.health||'neutral');
  const label=c.status==='active'?(lang==='es'?'Activa':'Active'):statusText(c.status||health);
  const draft=lang==='es'?`Muéstrame qué pasó estos días con ${c.name} y dime qué harías ahora.`:`Give me a timeline read for ${c.name}. What happened this week and what would you move now?`;
  const returnLabel=lang==='es'?`Vuelve ${Number(c.roas||0).toFixed(2)}x por cada $1`:`ROAS ${Number(c.roas||0).toFixed(2)}x`;
  return `<div class="timeline-row"><div><div class="timeline-name">${escapeHtml(demoCampaignName(c.name))}</div><div class="timeline-status">${label} · ${returnLabel}</div></div><div class="timeline-track"><button class="timeline-bar ${escapeHtml(health)}" data-style-code="left:${left}%;width:${width}%" data-action-code="openChat(${chatArg(draft)})"><span>${campaignInitials(demoCampaignName(c.name))}</span><span>${label}</span></button></div></div>`;
 }).join(''):`<p class="notice">${lang==='es'?'Cuando tengas anuncios activos, los verás aquí como una línea de tiempo visual.':'When ads are active, you will see them here as a visual timeline.'}</p>`;
 box.innerHTML=`<section class="timeline-shell"><div class="timeline-head"><div><h3>${lang==='es'?'Anuncios en el tiempo':'Active ads timeline'}</h3><p>${lang==='es'?'Una vista rápida para entender qué está corriendo, qué está pausado y dónde conviene preguntarle al agente.':'A fast view of what is running, what is paused, and where to ask the manager.'}</p></div><button class="btn ask-btn" data-action-code="openChat(${chatArg(lang==='es'?'Mira todos mis anuncios en el tiempo y dime cuál necesita atención hoy.':'Read the full timeline and tell me which campaign needs attention today.')})">${t('ask_agent')}</button></div><div class="timeline-scale"><span></span>${days.map(d=>`<span>${d}</span>`).join('')}</div>${rows}</section>`;
}
function renderAnalyticsView(){
 const box=qs('#view-analytics');if(!box)return;
 const m=state.metrics||{},s=m.summary||{},campaigns=m.campaigns||[];
 const total=Math.max(Number(s.total_spend||0)+Number(s.total_revenue||0)+Number(s.total_conversions||0),1);
 const trends=aggregateTrend(campaigns);
 const top=[...campaigns].sort((a,b)=>Number(b.roas||0)-Number(a.roas||0)).slice(0,6);
 const winner=top[0];
 const days=dayLabels();
 box.innerHTML=`<section class="analytics-grid"><div class="analytics-hero analytics-card"><div class="analytics-head"><div><h3>${lang==='es'?'Vista general':'Total overview'}</h3><p>${lang==='es'?'Lectura visual de inversión, resultados y movimiento de los últimos días.':'Visual read of spend, results, and recent movement.'}</p></div><span class="badge winning">+ ${Number(s.overall_roas||0).toFixed(2)}x</span></div><div class="analytics-legend"><div class="legend-row"><span class="legend-dot" data-style-code="background:#b9a8ff"></span><span>${t('spend')}</span><b>${fmtMoney(s.total_spend)}</b></div><div class="legend-track"><i class="legend-fill" data-style-code="display:block;width:${clamp(Number(s.total_spend||0)/total*100,8,100)}%"></i></div><div class="legend-row"><span class="legend-dot" data-style-code="background:#ffd55d"></span><span>${t('revenue')}</span><b>${fmtMoney(s.total_revenue)}</b></div><div class="legend-track"><i class="legend-fill" data-style-code="display:block;width:${clamp(Number(s.total_revenue||0)/total*100,8,100)}%"></i></div><div class="legend-row"><span class="legend-dot" data-style-code="background:#7fded5"></span><span>${t('conversions')}</span><b>${Number(s.total_conversions||0).toLocaleString()}</b></div><div class="legend-track"><i class="legend-fill" data-style-code="display:block;width:${clamp(Number(s.total_conversions||0)/total*100,8,100)}%"></i></div></div></div><div class="analytics-card"><div class="analytics-head"><div><h3>${lang==='es'?'Semana':'Week'}</h3><p>${lang==='es'?'Pulso diario de actividad.':'Daily activity pulse.'}</p></div></div><div class="calendar-mini">${days.map((d,i)=>{const v=Number(trends[i]||0),h=clamp(v/Math.max(...trends,1),.18,1);return `<div class="calendar-day"><span>${d}</span><div class="day-stack"><i class="day-seg a" data-style-code="height:${20*h}px"></i><i class="day-seg b" data-style-code="height:${34*h}px"></i><i class="day-seg c" data-style-code="height:${24*h}px"></i></div></div>`}).join('')}</div></div></section><section class="analytics-cards"><div class="analytics-card"><h4>${lang==='es'?'Señales del negocio':'Market signal'}</h4><strong>${fmtMoney(s.total_spend)}</strong><p class="notice">${lang==='es'?'Inversión leída por el agente para decidir con menos estrés.':'Spend read by the agent for calmer decisions.'}</p>${miniBars(trends)}</div><div class="analytics-card"><h4>${lang==='es'?'Resultados':'Efficiency'}</h4><strong>${Number(s.overall_roas||0).toFixed(2)}x</strong><p class="notice">${lang==='es'?'Resultado general con alertas de costo por compra y cansancio de anuncios.':'Global ROAS with CPA and fatigue alerts.'}</p>${spark(trends)}</div><div class="analytics-card"><h4>${lang==='es'?'Mejores campañas':'Top campaigns'}</h4><strong>${campaigns.length}</strong><p class="notice">${winner?`${escapeHtml(demoCampaignName(winner.name))} · ${Number(winner.roas||0).toFixed(2)}x`:lang==='es'?'Aún no hay campañas.':'No campaigns yet.'}</p><div class="avatar-row">${top.map(c=>`<span class="avatar-chip" title="${escapeHtml(demoCampaignName(c.name))}">${campaignInitials(demoCampaignName(c.name))}</span>`).join('')}</div></div></section>`;
}
function renderIdleView(){
 const box=qs('#view-idle');if(!box)return;
 const m=state.metrics||{},s=m.summary||{},p=state.business_profile||{};
 const offer=p.main_offer||p.offer||p.detected_title||(lang==='es'?'tu producto':'your product');
 const draft=lang==='es'?'Quiero crear una imagen showcase de mi producto para el modo idle. Usa mis guías de marca, pregúntame por la imagen de referencia si hace falta y prepara prompts consistentes.':'I want to create a product showcase image for idle mode. Use my brand guides, ask for the reference image if needed, and prepare consistent prompts.';
 box.innerHTML=`<section class="idle-hero"><div class="idle-grid"><div class="idle-copy"><div class="idle-head"><div><h3>${lang==='es'?'Hola, este es el pulso de ':'Hello, this is the pulse for '}<span>${escapeHtml(offer)}</span></h3><p>${lang==='es'?'Una vista tranquila para dejar abierta en pantalla: el agente sigue leyendo datos, cuidando señales y esperando que le hables como a un manager.':'A calm view to leave open: the agent keeps reading data, watching signals, and waiting for you to talk to it like a manager.'}</p></div></div><div class="showcase-actions"><button class="btn primary" data-action-code="openChat(${chatArg(draft)})">${lang==='es'?'Crear imagen del producto con Codex':'Create showcase with Codex'}</button><button class="btn ask-btn" data-action-code="openChat(${chatArg(lang==='es'?'Dime qué debería vigilar hoy en esta cuenta y qué harías tú ahora.':'Tell me what I should watch today in this account and what you would do now.')})">${t('ask_manager')}</button></div></div><div class="idle-product-stage"><div class="product-orb"></div><div class="idle-floating one"><b>${Number(s.overall_roas||0).toFixed(2)}x</b><span>${lang==='es'?'VUELVE / $1':'ROAS'}</span></div><div class="idle-floating two"><b>${fmtMoney(s.overall_cpa)}</b><span>${lang==='es'?'COSTO / COMPRA':'CPA'}</span></div><div class="idle-floating three"><b>${Number(s.total_conversions||0).toLocaleString()}</b><span>${t('conversions')}</span></div></div></div></section>`;
}
let unlockResolver=null;
let unlockMode='unlock';
function clearStoredDashboardSecrets(){localStorage.removeItem('dashboardPassword');localStorage.removeItem('dashboardToken');localStorage.removeItem('dashboardSession');sessionStorage.removeItem('dashboardSession')}
function dashboardPassword(){return localStorage.getItem('dashboardSession')||sessionStorage.getItem('dashboardSession')||localStorage.getItem('dashboardToken')||localStorage.getItem('dashboardPassword')||''}
function storeDashboardSession(result={},remember=true){const token=result.session_token||'';localStorage.removeItem('dashboardPassword');localStorage.removeItem('dashboardToken');localStorage.removeItem('dashboardSession');sessionStorage.removeItem('dashboardSession');if(token){(remember?localStorage:sessionStorage).setItem('dashboardSession',token);return token}return ''}
async function unlockWithPassword(value,remember=true){const res=await fetch('/api/unlock',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':value},body:JSON.stringify({remember_device:remember})});if(!res.ok)throw new Error(await responseErrorMessage(res));const data=await res.json();return storeDashboardSession(data.result||data,remember)||value}
function dashboardPasswordIsSet(){return !state||!state.config||state.config.dashboard_password_set!==false}
function setUnlockError(message=''){const err=qs('#unlock-error');if(err){err.textContent=message;err.classList.toggle('show',Boolean(message))}}
function syncUnlockMode(mode=''){unlockMode=mode||(dashboardPasswordIsSet()?'unlock':'create');const create=unlockMode==='create';const title=qs('#unlock-title'),body=qs('#unlock-body'),button=qs('#unlock-submit'),label=qs('#unlock-password-label'),confirmLabel=qs('#unlock-confirm-label'),input=qs('#unlock-password'),confirmInput=qs('#unlock-confirm-password'),confirmWrap=qs('#unlock-confirm-wrap');if(title){title.dataset.i18n=create?'unlock_create_title':'unlock_title';title.textContent=t(title.dataset.i18n)}if(body){body.dataset.i18n=create?'unlock_create_body':'unlock_body';body.textContent=t(body.dataset.i18n)}if(button){button.dataset.i18n=create?'unlock_create_button':'unlock_button';button.textContent=t(button.dataset.i18n)}if(label){label.dataset.i18n='dashboard_password';label.textContent=t('dashboard_password')}if(confirmLabel){confirmLabel.dataset.i18n='dashboard_password_confirm';confirmLabel.textContent=t('dashboard_password_confirm')}if(input){input.autocomplete=create?'new-password':'current-password';input.placeholder=create?(lang==='es'?'Crea una contraseña segura':'Create a secure password'):''}if(confirmInput){confirmInput.classList.toggle('hidden',!create);confirmInput.disabled=!create;confirmInput.placeholder=create?(lang==='es'?'Escríbela otra vez':'Type it again'):'';confirmInput.value=''}if(confirmWrap)confirmWrap.classList.toggle('hidden',!create)}
function showUnlock(message='',mode=''){const overlay=qs('#unlock-overlay');syncUnlockMode(mode);setUnlockError(message);overlay.classList.add('open');setTimeout(()=>qs('#unlock-password')?.focus(),30);return new Promise(resolve=>{unlockResolver=resolve})}
function hideUnlock(){qs('#unlock-overlay')?.classList.remove('open');setUnlockError('')}
function openOnboardingPasswordStep(){const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='password');if(idx>=0){setOnboardingFlowStep(idx);setTimeout(()=>qs('#new-dashboard-password')?.focus(),60)}}
async function requestUnlock(message=''){if(!dashboardPasswordIsSet()){hideUnlock();openOnboardingPasswordStep();return ''}return showUnlock(message||t('unlock_needed'),'unlock')}
async function responseErrorMessage(res){const text=await res.text();try{const data=JSON.parse(text);return data.error||data.detail||text}catch{return text}}
async function api(path,opts={}){const headers={'Content-Type':'application/json',...(opts.headers||{})};const password=dashboardPassword();if(password)headers['X-Dashboard-Token']=password;let res=await fetch(path,{...opts,headers});if(res.status===401){clearStoredDashboardSecrets();const entered=await requestUnlock();if(entered){headers['X-Dashboard-Token']=entered;res=await fetch(path,{...opts,headers});if(res.status===401){clearStoredDashboardSecrets();await requestUnlock(t('unlock_failed'));throw new Error(t('unlock_failed'))}}}if(!res.ok)throw new Error(await responseErrorMessage(res));return res.json()}
async function load(){const firstLoad=!state;if(firstLoad)setDashboardBooting(true);try{state=await api('/api/dashboard');if(!metricsRangeTouched)metricsRange=normalizeClientMetricsRange(state.metrics?.metrics_range);render();const canAccess=Boolean(uiWorkbenchPreview||!state.config.dashboard_password_required||(state.config.dashboard_password_set&&dashboardPassword()));if(!uiWorkbenchPreview&&state.config.dashboard_password_required&&!state.config.dashboard_password_set){clearStoredDashboardSecrets();hideUnlock()}else if(!uiWorkbenchPreview&&state.config.dashboard_password_required&&state.config.dashboard_password_set&&!dashboardPassword()&&state.onboarding&&state.onboarding.completed)showUnlock(t('unlock_needed'),'unlock');else if(!uiWorkbenchPreview&&state.onboarding?.completed)syncBrowserBriefTimezone();if(canAccess){openModelReconnectFromUrl();setTimeout(startDashboardIntroTourIfPending,350)}}finally{if(firstLoad)setDashboardBooting(false)}const canRefresh=Boolean(uiWorkbenchPreview||!state.config.dashboard_password_required||(state.config.dashboard_password_set&&dashboardPassword()));if(firstLoad)refreshAgentRuntimeStatus(false);if(canRefresh&&state.onboarding?.completed){if(firstLoad)setTimeout(()=>refreshInsights({silent:true}),700);startLiveMetricsAutoRefresh();startUpdateAutoCheck()}}

let agentRuntimeRefreshInFlight=false;
function mergeAgentRuntimeStatus(runtime={}){
 if(!state?.config)return;
 const main=runtime.main_codex_session||{},image=runtime.image_codex_session||main,imageStatus=runtime.codex_image_status||{},catalog=runtime.model_catalog||{},versions=runtime.runtime_versions||{};
 const model=state.config.agent_model||{};
 Object.assign(model,{
  hermes_model_options:Array.isArray(catalog.models)?catalog.models:model.hermes_model_options,
 hermes_model_recommended:catalog.recommended||model.hermes_model_recommended,
 hermes_model_catalog_source:catalog.source||model.hermes_model_catalog_source,
 hermes_model_catalog_updated_at:catalog.checked_at||model.hermes_model_catalog_updated_at,
  hermes_model_user_selected:Boolean(catalog.user_selected??model.hermes_model_user_selected),
  hermes_model_catalog_account_verified:Boolean(catalog.account_verified),
  hermes_model_catalog_auth_resolved:Boolean(catalog.auth_resolved),
  runtime_versions:versions,
  chatgpt_connected:Boolean(main.authenticated??main.ready),
  chatgpt_reauth_required:Boolean(main.reauth_required),
  chatgpt_auth_state:main.auth_state||'unknown',
  chatgpt_account:main.identity||{},
  chatgpt_session_detail:main.detail||'',
  codex_image_ready:Boolean(imageStatus.ok),
  codex_image_error:imageStatus.ok?'':(imageStatus.error||imageStatus.detail||''),
  codex_image_connected:Boolean(image.authenticated??image.ready),
  codex_image_account:image.identity||{},
  codex_image_session_detail:image.detail||''
 });
 state.config.agent_model=model;
 const studio=state.config.creative_studio||{};
 Object.assign(studio,{image_generation_ready:Boolean(imageStatus.ok),image_generation_provider:imageStatus.ok?'codex_image':'',codex_image_ready:Boolean(imageStatus.ok),codex_image_error:imageStatus.ok?'':(imageStatus.error||imageStatus.detail||''),codex_image_account:image.identity||{},codex_image_session_detail:image.detail||'',codex_image_connected:Boolean(image.authenticated??image.ready)});
 state.config.creative_studio=studio;
 renderChatGptPanel();
 if(qs('#onboarding-flow')?.classList.contains('open'))renderOnboardingFlow();
}
async function refreshAgentRuntimeStatus(force=false){
 if(agentRuntimeRefreshInFlight)return;
 agentRuntimeRefreshInFlight=true;
 try{const res=await api('/api/agent-model/runtime',{method:'POST',body:JSON.stringify({force:Boolean(force)})});mergeAgentRuntimeStatus(res.result||res||{})}catch(_err){}finally{agentRuntimeRefreshInFlight=false}
}

function browserTimezone(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone||''}catch{return ''}}
function dailyBriefTimeLabel(value){
 const match=String(value||'08:00').match(/^(\d{2}):(\d{2})$/);if(!match)return value||'08:00';
 const date=new Date(Date.UTC(2020,0,1,Number(match[1]),Number(match[2])));
 return new Intl.DateTimeFormat(lang==='es'?'es-CO':'en-US',{hour:'numeric',minute:'2-digit',timeZone:'UTC'}).format(date);
}
function renderDailyBriefScheduleButton(){
 const button=qs('#daily-brief-schedule-button'),label=qs('#daily-brief-schedule-label');if(!button||!label||!state)return;
 const schedule=state.config?.daily_brief||{},time=dailyBriefTimeLabel(schedule.time||'08:00');
 label.textContent=`Brief ${time}`;
 const zone=schedule.timezone||browserTimezone()||'UTC';
 button.title=lang==='es'?`Lectura diaria a las ${time}, hora local (${zone})`:`Daily brief at ${time}, local time (${zone})`;
 button.setAttribute('aria-label',button.title);
}
async function syncBrowserBriefTimezone(){
 if(dailyBriefTimezoneSyncStarted||!state?.onboarding?.completed)return;
 const timezone=browserTimezone();if(!timezone||state.config?.daily_brief?.timezone===timezone)return;
 dailyBriefTimezoneSyncStarted=true;
 try{
  const time=state.config?.daily_brief?.time||'08:00';
  const response=await api('/api/daily-brief/schedule',{method:'POST',body:JSON.stringify({time,timezone})});
  state.config.daily_brief={...state.config.daily_brief,time:response.time||time,timezone:response.timezone||timezone,cron:response.cron||{}};
  renderDailyBriefScheduleButton();
 }catch(err){console.warn('Could not synchronize daily brief timezone',err)}
}
function closeDailyBriefSchedule(){const box=qs('#guide-overlay');if(!box)return;box.classList.remove('open','product-tour','theme-choice','daily-brief-schedule-overlay');box.innerHTML=''}
function openDailyBriefSchedule(){
 const box=qs('#guide-overlay');if(!box||!state)return;
 const schedule=state.config?.daily_brief||{},timezone=browserTimezone()||schedule.timezone||'UTC';
 box.classList.remove('product-tour','theme-choice');box.classList.add('open','daily-brief-schedule-overlay');
 box.innerHTML=`<article class="daily-brief-schedule-card"><div class="next-step"><div><span class="tour-step-count">${lang==='es'?'Lectura diaria':'Daily brief'}</span><h2>${lang==='es'?'¿A qué hora quieres recibirla?':'What time should it arrive?'}</h2><p>${lang==='es'?'La hora usa automáticamente la zona local de este dispositivo.':'The time automatically uses this device’s local timezone.'}</p></div><button class="btn" type="button" data-action-code="closeDailyBriefSchedule()" aria-label="${lang==='es'?'Cerrar':'Close'}">×</button></div><form class="daily-brief-schedule-form" data-submit-code="saveDailyBriefSchedule(event)"><label>${lang==='es'?'Hora del brief':'Brief time'}<input name="time" type="time" required value="${escapeHtml(schedule.time||'08:00')}"></label><div class="daily-brief-timezone"><span aria-hidden="true">◎</span><div><b>${lang==='es'?'Hora local detectada':'Detected local time'}</b><p>${escapeHtml(timezone)}</p></div></div><button class="btn primary" type="submit">${lang==='es'?'Guardar hora':'Save time'}</button></form></article>`;
}
async function saveDailyBriefSchedule(event){
 event.preventDefault();const form=event.target,time=String(new FormData(form).get('time')||'').trim(),timezone=browserTimezone()||state.config?.daily_brief?.timezone||'UTC';
 const button=form.querySelector('button[type="submit"]');if(button){button.disabled=true;button.textContent=lang==='es'?'Guardando...':'Saving...'}
 try{
  const response=await api('/api/daily-brief/schedule',{method:'POST',body:JSON.stringify({time,timezone})});
  state.config.daily_brief={...state.config.daily_brief,time:response.time,timezone:response.timezone,cron:response.cron||{}};
  renderDailyBriefScheduleButton();closeDailyBriefSchedule();toast(lang==='es'?`Lectura diaria guardada para las ${dailyBriefTimeLabel(response.time)}.`:`Daily brief saved for ${dailyBriefTimeLabel(response.time)}.`);
 }catch(err){toast(err.message||String(err));if(button){button.disabled=false;button.textContent=lang==='es'?'Guardar hora':'Save time'}}
}
function decisionEvidenceMarkup(card){
 if(!card)return '';
 const ask=lang==='es'?`Explícame esta decisión sobre ${card.campaign_name||'mi campaña'} en palabras simples. Señal: ${card.signal||''}. Recomendación: ${card.recommendation||''}`:`Explain this decision about ${card.campaign_name||'my campaign'} in simple words. Signal: ${card.signal||''}. Recommendation: ${card.recommendation||''}`;
 return `<div class="brief-q decision-card"><b>${escapeHtml(card.title|| (lang==='es'?'Decisión con evidencia':'Decision with evidence'))}: ${escapeHtml(demoCampaignName(card.campaign_name||''))}</b><p>${escapeHtml(card.diagnosis||'')}</p><p><strong>${lang==='es'?'Señal':'Signal'}:</strong> ${escapeHtml(card.signal||'')}</p><p><strong>${lang==='es'?'Sugerencia':'Suggestion'}:</strong> ${escapeHtml(card.recommendation||'')}</p><p><strong>${lang==='es'?'Riesgo':'Risk'}:</strong> ${escapeHtml(card.risk||'')}</p><button class="btn ask-btn" data-action-code="openChat(${chatArg(ask)})">${t('ask_agent')}</button></div>`;
}
function decisionCardsMarkup(){
 const cards=state.decision_memory?.cards||[];
 if(!cards.length)return '';
 return `<div class="decision-memory-stack"><div class="next-step"><div><b>${lang==='es'?'Decisiones con evidencia':'Evidence-backed decisions'}</b><p>${lang==='es'?'El agente guarda por qué recomendó algo y lo revisa después de 24h, 3 días y 7 días.':'The agent saves why it recommended something and checks it again after 24h, 3 days, and 7 days.'}</p></div></div>${cards.slice(0,3).map(decisionEvidenceMarkup).join('')}</div>`;
}
function actionLabelText(text){
 if(lang!=='es')return text;
 return String(text||'')
  .replace(/^Paused (\d+) clear bleeder\(s\) after approval\.$/,'Pausé $1 gasto malo claro después de tu aprobación.')
  .replace(/^Prepared (\d+) creative refresh draft\(s\)\.$/,'Preparé $1 idea(s) nueva(s) para anuncios.')
  .replace(/^(\d+) pause decision\(s\) need buyer approval\.$/,'$1 pausa(s) necesitan tu aprobación.')
  .replace(/^(\d+) budget move\(s\) need buyer approval\.$/,'$1 cambio(s) de presupuesto necesitan tu aprobación.')
  .replace(/^(\d+) smaller budget move\(s\) are worth reviewing\.$/,'$1 movimiento(s) pequeños de presupuesto valen la pena revisar.')
  .replace(/^(\d+) fatigue signal\(s\) should feed the next creative test\.$/,'$1 señal(es) de cansancio deberían alimentar la próxima prueba creativa.')
  .replace('No strong action signal yet. Keep watching pacing, CPA, ROAS, CTR, and frequency.','Todavía no hay una señal fuerte para tocar Meta. Sigo vigilando ritmo de gasto, CPA, ROAS, clics y frecuencia.');
}
function actionSummaryMarkup(){
 const summary=state.brief?.action_summary||{};
 const buckets=[
  ['already_done',lang==='es'?'Ya hice':'Already done'],
  ['waiting_for_approval',lang==='es'?'Necesita tu luz verde':'Waiting for approval'],
  ['recommended_next',lang==='es'?'Siguiente movimiento':'Next move'],
  ['watching',lang==='es'?'Estoy vigilando':'Watching']
 ];
 const html=buckets.map(([key,title])=>{
  const items=summary[key]||[];if(!items.length)return '';
  return `<div class="brief-q action-bucket"><b>${title}</b>${items.map(item=>`<p>${escapeHtml(actionLabelText(item.label||''))}</p>`).join('')}</div>`;
 }).join('');
 return html?`<div class="decision-memory-stack action-summary-stack">${html}</div>`:'';
}
function render(){
 applyTranslations();
 renderDailyBriefScheduleButton();
 hydrateChatHistory();
 renderUpdateBanner(updateInfo);
 renderDeferredOnboardingBanner();
 const m=state.metrics, s=m.summary;const accountPriority=Array.isArray(m.account_priority_metrics)?m.account_priority_metrics.slice(0,4):[];const headerPriority=accountPriority.filter(row=>row.key!=='spend').slice(0,2);
 const headerOne=headerPriority[0]||accountPriority[0]||{label:'Results',label_es:'Resultados',format:'number',value:s.total_conversions,available:true};const headerTwo=headerPriority[1]||accountPriority[1]||{label:'Spend',label_es:'Gasto',format:'currency',value:s.total_spend,available:true};qs('#top-roas').textContent=priorityMetricLabel(headerOne);qs('#s-roas').textContent=priorityMetricValue(headerOne);qs('#top-cpa').textContent=priorityMetricLabel(headerTwo);qs('#s-cpa').textContent=priorityMetricValue(headerTwo); qs('#s-mode').textContent=modeText(state.config.mode); qs('#s-updated').textContent=new Date(m.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}); const versionEl=qs('#s-version');if(versionEl){versionEl.textContent=state.config?.product_version||state.version||'--';versionEl.closest('.version-pill')?.setAttribute('title',(lang==='es'?'Versión instalada: ':'Installed version: ')+versionEl.textContent)}
 renderMetricsRange();
 qs('#data-source-signal').textContent=dataSourceText(m);
 const refreshBtn=qs('#real-data-refresh');if(refreshBtn){refreshBtn.classList.toggle('hidden',m.source==='meta_graph');refreshBtn.textContent=lang==='es'?'Actualizar datos reales':'Refresh real data'}
 qs('#kpis').innerHTML=accountPriority.length?accountPriority.map(priorityKpi).join(''):[['Spend',fmtMoney(s.total_spend)],['Revenue',fmtMoney(s.total_revenue)],['Conversions',Number(s.total_conversions||0).toLocaleString()],['Active Budget',fmtMoney(s.active_budget)]].map(x=>kpi(x[0],x[1])).join('');
 renderBusinessProfilePanel();
 qs('#brief').innerHTML=state.brief.questions.map(q=>`<div class="brief-q"><b>${briefQuestion(q.question)}</b><p>${explainTerms(briefAnswer(q.answer))}</p></div>`).join('')+actionSummaryMarkup()+decisionCardsMarkup();
 qs('#fatigue').innerHTML=state.fatigue.length?state.fatigue.map(f=>`<div class="fatigue"><b>${escapeHtml(demoCampaignName(f.campaign_name))}</b><div>${escapeHtml(f.reasons.map(fatigueText).join(' / '))}</div></div>`).join(''):`<p class="notice">${t('no_fatigue')}</p>`;
 qs('#campaigns').innerHTML=m.campaigns.map(card).join('');
 renderOverviewViews();
 qs('#recs').innerHTML=state.recommendations.map(r=>{const draft=lang==='es'?`Revisa esta recomendación para ${r.campaign_name}. Estado: ${r.decision||'observe'}. ¿Qué evidencia falta o qué prepararías?`:`Review this recommendation for ${r.campaign_name}. State: ${r.decision||'observe'}. What evidence is missing or what would you prepare?`;const actionable=['increase_budget','decrease_budget'].includes(r.action)&&!r.shadow_mode;return `<tr><td>${escapeHtml(demoCampaignName(r.campaign_name))}<br><span class="notice">${escapeHtml(recommendationText(r.reason))}</span></td><td>${fmtMoney(r.current_budget)}</td><td>${fmtMoney(r.recommended_budget)}</td><td><button class="btn" ${actionable?'':'disabled'} data-action-code="applyRec('${r.campaign_id}',${r.recommended_budget})">${actionable?(r.requires_approval?t('request'):t('apply')):(r.shadow_mode?(lang==='es'?'Solo observación':'Shadow only'):(lang==='es'?'Observando':'Watching'))}</button><button class="btn ask-btn" data-style-code="margin-top:6px" data-action-code="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></td></tr>`}).join('');
 qs('#recs-mobile').innerHTML=state.recommendations.map(r=>{const draft=lang==='es'?`Revisa esta recomendación para ${r.campaign_name}. Estado: ${r.decision||'observe'}. ¿Qué evidencia falta o qué prepararías?`:`Review this recommendation for ${r.campaign_name}. State: ${r.decision||'observe'}. What evidence is missing or what would you prepare?`;const actionable=['increase_budget','decrease_budget'].includes(r.action)&&!r.shadow_mode;return `<div class="rec-card"><h3>${escapeHtml(demoCampaignName(r.campaign_name))}</h3><p class="notice">${escapeHtml(recommendationText(r.reason))}</p><div class="rec-values"><div><b>${fmtMoney(r.current_budget)}</b><span>${t('now')}</span></div><div><b>${fmtMoney(r.recommended_budget)}</b><span>${t('rec')}</span></div></div><button class="btn primary" ${actionable?'':'disabled'} data-action-code="applyRec('${r.campaign_id}',${r.recommended_budget})">${actionable?(r.requires_approval?t('request'):t('apply')):(r.shadow_mode?(lang==='es'?'Solo observación':'Shadow only'):(lang==='es'?'Observando':'Watching'))}</button><button class="btn ask-btn" data-style-code="margin-top:7px" data-action-code="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div>`}).join('');
 qs('#pending').innerHTML=state.pending.length?`<div class="approval-stack">${state.pending.map(approvalCard).join('')}</div>`:`<p class="notice">${t('no_pending')}</p>`;
 qs('#actions').innerHTML=state.actions.length?state.actions.map(a=>`<div class="log-item"><b>${actionName(a.type)}</b> - ${statusText(a.status)}<br>${new Date(a.created_at).toLocaleString()}${actionDetail(a)}</div>`).join(''):`<p class="notice">${t('no_actions')}</p>`;
 qs('#report-rows').innerHTML=m.campaigns.map(c=>`<tr><td>${escapeHtml(demoCampaignName(c.name))}</td><td>${adaptiveReportCell(c,0)}</td><td>${adaptiveReportCell(c,1)}</td><td>${adaptiveReportCell(c,2)}</td><td>${adaptiveReportCell(c,3)}</td><td>${statusText(c.health)}</td></tr>`).join('');
 renderCreativeStudio();
 renderSetup();
 renderAudience();
 renderOnboardingFlow();
}
let brandEditorMode='general';
let brandEditorProductId='';
let brandAdBriefProductGuide='';
function brandProductById(id){return (state.brand_guides?.products||[]).find(product=>product.id===id)}
function brandAdBriefById(id){return (state.brand_guides?.ad_briefs||[]).find(brief=>brief.id===id)}
function openBrandMemory(mode='general',itemId=''){
 brandEditorMode=mode;brandEditorProductId=itemId||'';
 qs('#brand-memory-overlay')?.classList.add('open');
 renderBrandMemoryModal();
}
function closeBrandMemory(){qs('#brand-memory-overlay')?.classList.remove('open')}
function memoryField(name,label,value='',placeholder='',wide=false,area=false){
 const classes=`brand-field${wide?' wide':''}`;
 const content=area?`<textarea name="${name}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value)}</textarea>`:`<input name="${name}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}">`;
 return `<label class="${classes}"><span>${escapeHtml(label)}</span>${content}</label>`;
}
function memorySelect(name,label,value='',options=[]){
 return `<label class="brand-field"><span>${escapeHtml(label)}</span><select name="${name}"><option value="">${lang==='es'?'Sin producto fijo':'No fixed product'}</option>${options.map(option=>`<option value="${escapeHtml(option.value)}" ${option.value===value?'selected':''}>${escapeHtml(option.label)}</option>`).join('')}</select></label>`;
}
function memoryWizardCta(kind,itemId=''){
 const labels={
  general:[lang==='es'?'Contarle cómo es mi marca':'Tell the agent about my brand',lang==='es'?'Te hará preguntas fáciles y lo recordará cuando cree anuncios.':'It asks simple questions and saves your answers for future ads.'],
  product:[lang==='es'?'Contarle qué vendo':'Tell it about my product',lang==='es'?'Te pregunta sobre tu producto, sin hacerte llenar casillas.':'Explain it in chat instead of filling every field.'],
  ad_brief:[lang==='es'?'Hablar y crear mi anuncio':'Create the idea with the agent',lang==='es'?'Dile qué quieres mostrar. El agente hará preguntas fáciles y preparará tu idea.':'It asks what you want to advertise and prepares a clear idea for your images and text.']
 };
 const copy=labels[kind]||labels.general;
 return `<div class="memory-wizard-cta"><div><b>${copy[0]}</b><p>${copy[1]}</p></div><button class="btn primary ask-btn" type="button" data-action-code="startCreativeMemoryWizard(${chatArg(kind)},${chatArg(itemId)},${chatArg(lang)})">${lang==='es'?'Empezar a hablar':'Answer in chat'}</button></div>`;
}
function startCreativeMemoryWizard(kind,itemId='',draftLang=''){
 const productGuide=kind==='ad_brief'?brandAdBriefProductGuide:'';
 closeBrandMemory();
 const es=(draftLang||uiLang())==='es';
 const labels={
  general:es?'Quiero contarte cómo es mi marca. Hazme preguntas fáciles, una a la vez, y recuerda mis respuestas para los anuncios.':'I want to complete my general brand memory with you. Ask simple questions and save it at the end.',
  product:es?'Quiero contarte qué vendo. Hazme preguntas fáciles, una a la vez, y recuerda mis respuestas para los anuncios.':'I want to create a product or offer sheet with you. Ask simple questions and save it at the end.',
  ad_brief:es?'Quiero preparar una idea para un anuncio contigo. Pregúntame qué vendo, qué oferta quiero mostrar, a quién quiero llegar y qué imágenes o textos quiero preparar. Al final guarda la idea.':'I want to prepare an ad idea with you. Ask what I sell, what offer I want to show, who I want to reach, and what images or text I want prepared. Save the idea at the end.'
 };
 sendChatMessage(labels[kind]||labels.general,{workspace:true,memoryWizard:{mode:'start',kind,id:itemId||'',product_guide:productGuide}});
}
const brandLogoPreviewUrls=new Map();
function brandLogoMarkup(fields){
 const logoPath=String(fields.logo_path||'').trim();
 const logoUrl=logoPath?`/api/brand-asset?id=${encodeURIComponent(logoPath)}`:'';
 const status=logoPath?(lang==='es'?'Logo guardado':'Logo saved'):(lang==='es'?'Sin logo todavía':'No logo yet');
 const preview=logoUrl?`<img alt="${lang==='es'?'Logo guardado':'Saved logo'}" data-brand-logo-url="${escapeHtml(logoUrl)}" hidden>`:`<span>${lang==='es'?'Logo':'Logo'}</span>`;
 return `<section class="brand-logo-card ${logoPath?'ready':''}"><div class="brand-logo-preview">${preview}</div><div class="brand-logo-copy"><span>${escapeHtml(status)}</span><h4>${lang==='es'?'Logo para tus anuncios':'Logo for your ads'}</h4><p>${lang==='es'?'Sube tu logo una vez. El agente lo usará como referencia cuando cree imágenes para que no invente una marca distinta.':'Upload the logo once. The manager uses it as visual context when creating ad images.'}</p><div class="brand-logo-actions"><label class="btn primary brand-logo-upload">${lang==='es'?'Subir logo':'Upload logo'}<input class="hidden" type="file" accept="image/png,image/jpeg,image/webp" data-change-code="uploadBrandLogo(event)"></label>${logoPath?`<span class="brand-logo-path">${escapeHtml(logoPath)}</span>`:''}</div></div><label class="brand-field wide brand-logo-notes"><span>${lang==='es'?'Notas del logo':'Logo notes'}</span><textarea name="logo_notes" placeholder="${lang==='es'?'Ej: logo circular azul, siempre sobre fondo claro':'Example: blue circular logo, always on light background'}">${escapeHtml(fields.logo_notes||'')}</textarea></label></section>`;
}
async function hydrateBrandLogoPreviews(){
 const images=[...document.querySelectorAll('img[data-brand-logo-url]')];
 for(const image of images){
  const path=image.dataset.brandLogoUrl;if(!path)continue;
  try{
   if(!brandLogoPreviewUrls.has(path)){const response=await fetchProtectedFile(path);brandLogoPreviewUrls.set(path,URL.createObjectURL(await response.blob()))}
   image.src=brandLogoPreviewUrls.get(path);image.hidden=false;
  }catch(err){image.hidden=true}
 }
}
function readFileAsDataUrl(file){
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(reader.result);
  reader.onerror=()=>reject(reader.error||new Error('file_read_failed'));
  reader.readAsDataURL(file);
 });
}
async function uploadBrandLogo(event){
 const input=event.target;const file=input.files?.[0];if(!file)return;
 input.value='';
 if(!/^image\/(png|jpe?g|webp)$/i.test(file.type||'')){toast(lang==='es'?'Sube un logo PNG, JPG o WebP.':'Upload a PNG, JPG, or WebP logo.');return}
 if(file.size>1024*1024){toast(lang==='es'?'Usa un logo menor a 1 MB.':'Use a logo smaller than 1 MB.');return}
 const notes=qs('#brand-memory-editor textarea[name="logo_notes"]')?.value||'';
 const dataUrl=await readFileAsDataUrl(file);
 const res=await api('/api/brand-guides/logo',{method:'POST',body:JSON.stringify({filename:file.name,content_type:file.type,data_url:dataUrl,logo_notes:notes})});
 state.brand_guides=res.result.library||state.brand_guides;
 brandEditorMode='general';
 toast(lang==='es'?'Logo guardado para tus creativos':'Logo saved for your creatives');
 renderCreativeStudio();
}
function generalMemoryForm(fields){
 return `<div class="brand-editor-intro"><h3>${lang==='es'?'Cómo es tu marca':'Your brand foundation'}</h3><p>${lang==='es'?'Cuéntale al agente cómo quieres que se vean y suenen tus anuncios.':'The manager learns this once and respects it across every product creative.'}</p>${memoryWizardCta('general')}</div><form class="brand-editor-form" data-submit-code="saveGeneralMemory(event)">${brandLogoMarkup(fields)}<section class="brand-form-section"><h4>${lang==='es'?'Sobre tu negocio':'Business'}</h4><div class="brand-form-grid">${memoryField('brand_name',lang==='es'?'Nombre de tu marca':'Brand name',fields.brand_name,'Miro Ads')}${memoryField('offer',lang==='es'?'Qué vendes':'What you sell',fields.offer,'Cursos, productos o servicios')}${memoryField('promise',lang==='es'?'Qué ayudas a conseguir':'Main promise',fields.promise,'El cambio que busca tu comprador',true,true)}${memoryField('ideal_customer',lang==='es'?'A quién quieres ayudar':'Ideal customer',fields.ideal_customer,'Quién compraría tu producto',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Cómo deben verse tus anuncios':'Visual style'}</h4><div class="brand-form-grid">${memoryField('colors',lang==='es'?'Colores que usas':'Core colors',fields.colors,'Rosa suave, blanco, turquesa')}${memoryField('visual_style',lang==='es'?'Cómo quieres que se vean':'How it should look',fields.visual_style,'Limpio, sencillo, con el producto visible',true,true)}${memoryField('logo_usage',lang==='es'?'Cuándo usar el logo':'When to use the logo',fields.logo_usage,'Siempre, a veces o nunca',true,true)}${memoryField('references',lang==='es'?'Diseños de referencia':'Visual references',fields.references,'Sube o describe ejemplos; también puedes decir que no tienes',true,true)}${memoryField('asset_notes',lang==='es'?'Fotos y activos reales':'Real photos and assets',fields.asset_notes,'Producto, fundador, clientes, local, empaque o ninguno',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Cómo debe hablar':'Voice and boundaries'}</h4><div class="brand-form-grid">${memoryField('tone',lang==='es'?'Cómo quieres que suene':'How it should sound',fields.tone,'Cercano, seguro y simple',true,true)}${memoryField('show_always',lang==='es'?'Qué siempre debe mostrar':'Always show',fields.show_always,'Producto, beneficio claro, personas reales',true,true)}${memoryField('avoid_always',lang==='es'?'Qué nunca debe mostrar ni decir':'Always avoid',fields.avoid_always,'Promesas que no puedes probar o demasiado texto',true,true)}</div></section><div class="brand-form-save"><button class="btn primary" type="submit">${lang==='es'?'Guardar mi marca':'Save brand memory'}</button></div></form>`;
}
function productMemoryForm(fields,product){
 const hidden=product?`<input type="hidden" name="id" value="${escapeHtml(product.id)}">`:'';
 return `<div class="brand-editor-intro"><h3>${product?(lang==='es'?'Datos de tu producto':'Product details'):(lang==='es'?'Nuevo producto o promoción':'New product or offer')}</h3><p>${lang==='es'?'El agente usa esto para crear anuncios sobre lo que de verdad vendes.':'The manager uses these details so images and text match the right product.'}</p>${memoryWizardCta('product',product?.id||'')}${product?`<div class="brand-editor-actions"><button class="btn primary" type="button" data-action-code="refreshForProduct(${chatArg(product.id)})">${lang==='es'?'Crear ideas de anuncios':'Create ad ideas'}</button><button class="btn" type="button" data-action-code="startAdBriefForProduct(${chatArg(product.id)})">${lang==='es'?'Crear un anuncio para este producto':'Create an ad for this product'}</button><button class="btn" type="button" data-action-code="chatForProduct(${chatArg(product.id)},${chatArg(lang)})">${lang==='es'?'Hablar con el agente':'Talk with the agent'}</button></div>`:''}</div><form class="brand-editor-form" data-submit-code="saveProductMemory(event)">${hidden}<section class="brand-form-section"><h4>${lang==='es'?'Lo que vendes':'Offer'}</h4><div class="brand-form-grid">${memoryField('name',lang==='es'?'Nombre del producto':'Product name',fields.name,'Curso de anuncios para tiendas')}${memoryField('url',lang==='es'?'Página donde pueden comprar':'Sales page',fields.url,'https://...')}${memoryField('price',lang==='es'?'Precio':'Price or range',fields.price,'USD $49')}${memoryField('includes',lang==='es'?'Qué recibe la persona':'What is included',fields.includes,'Describe lo que recibe',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Quién lo compra':'Buyer and transformation'}</h4><div class="brand-form-grid">${memoryField('audience',lang==='es'?'Para quién es':'Who it is for',fields.audience,'A quién quieres atraer',true,true)}${memoryField('pain',lang==='es'?'Qué problema tiene':'Pain they feel',fields.pain,'Qué le preocupa hoy',true,true)}${memoryField('desire',lang==='es'?'Qué quiere conseguir':'Desired outcome',fields.desire,'Qué desea conseguir',true,true)}${memoryField('objections',lang==='es'?'Qué duda puede tener':'Buying objections',fields.objections,'Precio, confianza, tiempo...',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Ideas para mostrarlo':'Angles and creative rules'}</h4><div class="brand-form-grid">${memoryField('angle_pain',lang==='es'?'Mostrar su problema':'Pain angle',fields.angle_pain,'Cómo mostrar el problema',true,true)}${memoryField('angle_desire',lang==='es'?'Mostrar el resultado':'Desire angle',fields.angle_desire,'Cómo mostrar el resultado',true,true)}${memoryField('angle_trust',lang==='es'?'Dar confianza':'Trust angle',fields.angle_trust,'Reseñas, datos reales o tranquilidad',true,true)}${memoryField('show',lang==='es'?'Qué debe mostrar':'Show',fields.show,'Producto, personas, detalle visual',true,true)}${memoryField('avoid',lang==='es'?'Qué no debe aparecer':'Do not show',fields.avoid,'Lo que dañaría la marca',true,true)}${memoryField('strong_phrases',lang==='es'?'Frases que puede usar':'Approved phrases',fields.strong_phrases,'Mensajes que sí puedes prometer',true,true)}</div></section><div class="brand-form-save"><button class="btn primary" type="submit">${lang==='es'?'Guardar producto':'Save product details'}</button></div></form>`;
}
function adBriefMemoryForm(fields,brief){
 const products=state.brand_guides?.products||[];
 const productValue=fields.product_guide||brandAdBriefProductGuide||'';
 const productOptions=products.map(product=>({value:product.guide,label:product.name}));
 const hidden=brief?`<input type="hidden" name="id" value="${escapeHtml(brief.id)}">`:'';
 const manualForm=`<form class="brand-editor-form" data-submit-code="saveAdBriefMemory(event)">${hidden}<section class="brand-form-section"><h4>${lang==='es'?'Lo básico':'The basics'}</h4><div class="brand-form-grid">${memoryField('name',lang==='es'?'Nombre de esta idea':'Idea name',fields.name,'Promo de junio')}${memorySelect('product_guide',lang==='es'?'Qué vendes':'Product/offer',productValue,productOptions)}${memoryField('adset_name',lang==='es'?'Quién debe ver el anuncio':'Audience',fields.adset_name,'Mujeres de 25 a 44 años en Colombia')}${memoryField('objective',lang==='es'?'Qué quieres que hagan':'Goal',fields.objective,'Comprar, escribirte, reservar...')}${memoryField('promotion',lang==='es'?'Qué quieres mostrarles':'Promotion or specific idea',fields.promotion,'2x1, lanzamiento, bono, temporada...',true,true)}${memoryField('audience_slice',lang==='es'?'Qué les importa o preocupa':'Audience needs',fields.audience_slice,'Qué buscan o qué les preocupa',true,true)}</div></section><section class="brand-form-section"><h4>${lang==='es'?'Lo que puede cambiar':'Options to try'}</h4><div class="brand-form-grid">${memoryField('base_ad',lang==='es'?'Qué ya te funcionó':'What already works',fields.base_ad,'Imagen, frase, testimonio u oferta...',true,true)}${memoryField('locked_elements',lang==='es'?'Qué no debe cambiar':'Do not change',fields.locked_elements,'Precio, oferta, producto o frase...',true,true)}${memoryField('variation_window',lang==='es'?'Quieres una idea o varias opciones':'Creative options',fields.variation_window,'Ej: una idea, o tres opciones cambiando colores',true,true)}${memoryField('variation_axes',lang==='es'?'Qué se puede cambiar':'What can vary',fields.variation_axes,'Colores, fondo, foto o título',true,true)}${memoryField('variation_count',lang==='es'?'Cuántas opciones preparar':'Number of options',fields.variation_count,'1')}${memoryField('creative_hypothesis',lang==='es'?'Qué quieres comparar':'What to compare',fields.creative_hypothesis,'Ej: si una foto clara recibe más clics',true,true)}${memoryField('agent_notes',lang==='es'?'Algo más que deba saber':'Manager notes',fields.agent_notes,'Cualquier detalle importante',true,true)}</div></section><details class="brand-advanced"><summary>${lang==='es'?'Solo si ya tienes anuncios en Meta':'Only if you already have Meta ads'}</summary><section class="brand-form-section"><div class="brand-form-grid">${memoryField('campaign_name',lang==='es'?'Nombre de la campaña anterior':'Campaign',fields.campaign_name,'Opcional')}${memoryField('base_ad_name',lang==='es'?'Nombre del anuncio que quieres mejorar':'Base ad',fields.base_ad_name,'Opcional')}${memoryField('base_ad_id',lang==='es'?'Número del anuncio, si lo conoces':'Base ad ID',fields.base_ad_id,'Opcional')}</div></section></details><div class="brand-form-save"><button class="btn primary" type="submit">${lang==='es'?'Guardar esta idea':'Save ad idea'}</button></div></form>`;
 return `<div class="brand-editor-intro"><h3>${brief?(lang==='es'?'Tu idea de anuncio':'Ad idea'):(lang==='es'?'Crear un anuncio':'New ad idea')}</h3><p>${lang==='es'?'Puedes explicárselo al agente hablando, como se lo contarías a una persona. Él organizará la información por ti.':'Describe what you want to advertise, who you want to reach, and which images or text you want prepared.'}</p>${memoryWizardCta('ad_brief',brief?.id||'')}${brief?`<div class="brand-editor-actions"><button class="btn primary" type="button" data-action-code="refreshForAdBrief(${chatArg(brief.id)})">${lang==='es'?'Crear imágenes y textos':'Create images and text'}</button><button class="btn" type="button" data-action-code="chatForAdBrief(${chatArg(brief.id)},${chatArg(lang)})">${lang==='es'?'Pedir cambios al agente':'Ask the agent for changes'}</button></div>`:''}</div><details class="memory-manual-entry" ${brief?'open':''}><summary><span>${lang==='es'?'Prefiero escribir los detalles yo':'I prefer to enter details myself'}<small class="memory-manual-help">${lang==='es'?'Opcional: el agente puede preguntarte todo en el chat.':'Optional: the agent can ask you everything in chat.'}</small></span></summary>${manualForm}</details>`;
}
function advancedMemoryFields(mode,fields){
 if(mode==='general')return `<details class="brand-advanced"><summary>${lang==='es'?'Más detalles, si los quieres agregar':'Optional brand details'}</summary><section class="brand-form-section"><div class="brand-form-grid">${memoryField('category',lang==='es'?'Tipo de negocio':'Category',fields.category,'Belleza, educación, servicios...')}${memoryField('market',lang==='es'?'País o ciudad principal':'Main market',fields.market,'México, Colombia...')}${memoryField('website',lang==='es'?'Página web':'Website',fields.website,'https://...')}${memoryField('personality',lang==='es'?'Cómo se siente tu marca':'Personality',fields.personality,'Elegante, práctica, atrevida...',true,true)}${memoryField('avoid_colors',lang==='es'?'Colores que no quieres':'Colors to avoid',fields.avoid_colors,'')}${memoryField('typography',lang==='es'?'Tipo de letras que te gusta':'Typography style',fields.typography,'')}${memoryField('energy',lang==='es'?'Sensación que debe dar':'Energy level',fields.energy,'Tranquila, alegre, fuerte...')}${memoryField('sales_energy',lang==='es'?'Qué tan directa debe vender':'Sales intensity',fields.sales_energy,'Directa sin promesas falsas',true,true)}${memoryField('words_use',lang==='es'?'Palabras que sí usa tu marca':'Words to use',fields.words_use,'',true,true)}${memoryField('words_avoid',lang==='es'?'Palabras que no quieres usar':'Words to avoid',fields.words_avoid,'',true,true)}${memoryField('authority',lang==='es'?'Pruebas que puedes mostrar':'Allowed proof',fields.authority,'Reseñas o cifras reales...',true,true)}</div></section></details>`;
 return `<details class="brand-advanced"><summary>${lang==='es'?'Más detalles, si los quieres agregar':'Optional product details'}</summary><section class="brand-form-section"><div class="brand-form-grid">${memoryField('not_for',lang==='es'?'Para quién no es':'Who it is not for',fields.not_for,'',true,true)}${memoryField('before_buying',lang==='es'?'Qué piensa antes de comprar':'Before buying thought',fields.before_buying,'',true,true)}${memoryField('after_buying',lang==='es'?'Cómo quiere sentirse después':'After buying feeling',fields.after_buying,'',true,true)}${memoryField('angle_urgency',lang==='es'?'Cómo mostrar que es el momento':'Urgency angle',fields.angle_urgency,'',true,true)}${memoryField('angle_education',lang==='es'?'Qué necesita entender primero':'Educational angle',fields.angle_education,'',true,true)}${memoryField('avoid_phrases',lang==='es'?'Frases que no debe usar':'Phrases to avoid',fields.avoid_phrases,'',true,true)}</div></section></details>`;
}
function renderBrandMemoryModal(){
 const overlay=qs('#brand-memory-overlay');if(!overlay?.classList.contains('open'))return;
 const memory=state.brand_guides||{};const products=memory.products||[];const adBriefs=memory.ad_briefs||[];
 qs('#brand-memory-kicker').textContent=lang==='es'?'El agente recuerda esto':'Manager memory';
 qs('#brand-memory-title').textContent=lang==='es'?'Tu marca, lo que vendes y tus anuncios':'Brand, products, and ads';
 qs('#brand-memory-subtitle').textContent=lang==='es'?'Cuéntale estas cosas al agente para que cree imágenes y textos que sí se parezcan a tu negocio.':'Save how your brand looks, what you sell, and which ad you want to prepare. This helps the agent create relevant images and text.';
 const activeGeneral=brandEditorMode==='general';const activeProduct=brandEditorMode==='product';const activeAdBrief=brandEditorMode==='ad_brief';
 qs('#brand-memory-nav').innerHTML=`<span class="brand-nav-label">${lang==='es'?'Tu marca':'Base'}</span><button class="brand-nav-item ${activeGeneral?'active':''}" type="button" data-action-code="openBrandMemory('general')"><span><b>${lang==='es'?'Cómo se ve mi marca':'General brand'}</b><small>${memory.general?.saved?(lang==='es'?'Guardado':'Saved'):(lang==='es'?'Completar':'Complete')}</small></span><span class="brand-ready ${memory.general?.saved?'':'draft'}">${memory.general?.saved?'OK':'...'}</span></button><span class="brand-nav-label">${lang==='es'?'Productos':'Products'}</span>${products.map(product=>`<button class="brand-nav-item ${activeProduct&&brandEditorProductId===product.id?'active':''}" type="button" data-action-code="openBrandMemory('product',${chatArg(product.id)})"><span><b>${escapeHtml(product.name)}</b><small>${product.ready?(lang==='es'?'Listo':'Ready'):(lang==='es'?'Falta detalle':'Needs details')}</small></span><span class="brand-ready ${product.ready?'':'draft'}">${product.ready?'OK':'...'}</span></button>`).join('')}<button class="btn brand-new-product" type="button" data-action-code="openBrandMemory('product','')">${lang==='es'?'+ Producto':'+ New product'}</button><span class="brand-nav-label">${lang==='es'?'Anuncios':'Ad ideas'}</span>${adBriefs.map(brief=>`<button class="brand-nav-item ${activeAdBrief&&brandEditorProductId===brief.id?'active':''}" type="button" data-action-code="openBrandMemory('ad_brief',${chatArg(brief.id)})"><span><b>${escapeHtml(brief.name)}</b><small>${escapeHtml(brief.adset_name||brief.campaign_name||brief.base_ad_name||(lang==='es'?'Idea guardada':'Saved idea'))}</small></span><span class="brand-ready ${brief.ready?'':'draft'}">${brief.ready?'OK':'...'}</span></button>`).join('')}<button class="btn brand-new-product" type="button" data-action-code="openBrandMemory('ad_brief','')">${lang==='es'?'+ Anuncio':'+ Ad idea'}</button>`;
 const selected=brandProductById(brandEditorProductId);
 const selectedBrief=brandAdBriefById(brandEditorProductId);
 const fields=activeGeneral?(memory.general?.fields||{}):(activeProduct?(selected?.fields||{}):(selectedBrief?.fields||{}));
 qs('#brand-memory-editor').innerHTML=activeGeneral?generalMemoryForm(fields):(activeProduct?productMemoryForm(fields,selected):adBriefMemoryForm(fields,selectedBrief));
 if(!activeAdBrief)qs('#brand-memory-editor .brand-form-save')?.insertAdjacentHTML('beforebegin',advancedMemoryFields(activeGeneral?'general':'product',fields));
 if(activeGeneral)hydrateBrandLogoPreviews();
}
function renderBrandGuides(){
 const box=qs('#brand-guides-panel');if(!box)return;
 const memory=state.brand_guides||{};const products=memory.products||[];const adBriefs=memory.ad_briefs||[];
 const status=memory.general?.saved?(lang==='es'?'Marca guardada':'Brand saved'):(lang==='es'?'Completa tu marca':'Complete your brand');
 box.innerHTML=`<div class="brand-vault-strip"><div class="brand-vault-summary"><span class="brand-vault-mark">AI</span><div><b>${lang==='es'?'Lo que el agente recuerda':'Ad creative memory'}</b><p>${escapeHtml(status)} · ${lang==='es'?`${products.length} producto${products.length===1?'':'s'} · ${adBriefs.length} idea${adBriefs.length===1?'':'s'} de anuncio`:`${products.length} product${products.length===1?'':'s'} · ${adBriefs.length} ad idea${adBriefs.length===1?'':'s'}`}</p>${(products.length||adBriefs.length)?`<div class="brand-vault-pills">${products.slice(0,2).map(product=>`<span class="brand-vault-pill ${product.ready?'ready':''}">${escapeHtml(product.name)}</span>`).join('')}${adBriefs.slice(0,2).map(brief=>`<span class="brand-vault-pill ${brief.ready?'ready':''}">${escapeHtml(brief.name)}</span>`).join('')}</div>`:''}</div></div><div class="brand-vault-actions"><button class="btn primary" type="button" data-action-code="openBrandMemory('ad_brief','')">${lang==='es'?'Nueva idea':'New idea'}</button><button class="btn" type="button" data-action-code="openBrandMemory('general')">${lang==='es'?'Mi marca':'Memory'}</button><button class="btn" type="button" data-action-code="openBrandMemory('product','')">${lang==='es'?'+ Producto':'+ Product'}</button></div></div>`;
 renderBrandMemoryModal();
}
async function saveGeneralMemory(event){
 event.preventDefault();
 const res=await api('/api/brand-guides/general',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target).entries()))});
 state.brand_guides=res.result;toast(lang==='es'?'Memoria de marca guardada':'Brand memory saved');renderCreativeStudio();
}
async function saveProductMemory(event){
 event.preventDefault();
 const res=await api('/api/brand-guides/product',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target).entries()))});
 state.brand_guides=res.result.library;brandEditorMode='product';brandEditorProductId=res.result.product_id;
 toast(lang==='es'?'Ficha del producto guardada':'Product sheet saved');renderCreativeStudio();
}
async function saveAdBriefMemory(event){
 event.preventDefault();
 const res=await api('/api/ad-briefs',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target).entries()))});
 state.brand_guides=res.result.library;brandEditorMode='ad_brief';brandEditorProductId=res.result.ad_brief_id;brandAdBriefProductGuide='';
 toast(lang==='es'?'Idea de anuncio guardada':'Ad idea saved');renderCreativeStudio();
}
function startAdBriefForProduct(productId){
 const product=brandProductById(productId);brandAdBriefProductGuide=product?.guide||'';openBrandMemory('ad_brief','');
}
function chatForProduct(productId,draftLang=''){
 const product=brandProductById(productId);if(!product)return;
 closeBrandMemory();
 const es=(draftLang||uiLang())==='es';
 openChat(es?`Quiero preparar anuncios para ${product.name}. Usa los datos guardados de este producto y pregúntame solo lo que falte antes de proponer imágenes y textos.`:`I want to prepare ads for ${product.name}. Use this product's saved details and ask only for anything missing before proposing images and text.`);
}
function chatForAdBrief(briefId,draftLang=''){
 const brief=brandAdBriefById(briefId);if(!brief)return;
 closeBrandMemory();
 const es=(draftLang||uiLang())==='es';
 openChat(es?`Quiero trabajar en la idea de anuncio ${brief.name}. Usa lo que ya guardé y ayúdame a preparar imágenes y textos. Si falta algo, pregúntame una sola cosa a la vez.`:`I want to work on the ${brief.name} ad idea. Use what I already saved and help me prepare images and text. Ask one question at a time if anything is missing.`);
}
async function refreshForProduct(productId){
 const product=brandProductById(productId);if(!product)return;
 closeBrandMemory();await generateRefresh('',product.guide);
}
async function refreshForAdBrief(briefId){
 const brief=brandAdBriefById(briefId);if(!brief)return;
 closeBrandMemory();await generateRefresh('','',brief.guide);
}
const creativePreviewUrls=new Map();
function creativeStatus(value){
 const labels={dry_run:lang==='es'?'Ideas listas':'Ideas ready',needs_codex_image:lang==='es'?'Listo para Codex/Image':'Ready for Codex/Image',images_ready:lang==='es'?'Imágenes listas':'Images ready',partially_generated:lang==='es'?'Revisar imágenes':'Review images',generation_failed:lang==='es'?'Falló la imagen':'Image failed'};
 return labels[value]||statusText(value);
}
function creativeMissingText(value){
 const raw=String(value||'');
 if(lang!=='es')return raw;
 if(raw.includes('generated image asset'))return 'Falta generar la imagen final';
 if(raw.includes('default_adset_id'))return 'Falta elegir dónde irá este anuncio';
 if(raw.includes('page_id'))return 'Falta página de Facebook';
 if(raw.includes('META_AD_ACCOUNT_ID'))return 'Falta cuenta publicitaria';
 return raw;
}
function demoCreativeText(value){
 if(lang!=='es'||state?.metrics?.source!=='demo')return String(value||'');
 return String(value||'').replaceAll('Brand Awareness Campaign','Campaña para dar a conocer la marca')
  .replaceAll('Q2 Conversion Campaign','Campaña de ventas Q2')
  .replaceAll('Premium product or service','este producto');
}
function creativeStorageNote(asset){
 if(!asset)return '';
 if(asset.saved_for_ad)return `<span class="creative-retention-note saved">${lang==='es'?'Guardada por usarse en anuncio':'Saved because it is used in an ad'}</span>`;
 return `<span class="creative-retention-note">${lang==='es'?'Guardada localmente. Puedes descargarla o limpiar borradores.':'Saved locally. You can download it or clear drafts.'}</span>`;
}
function creativeStorageReminderMarkup(policy){
 const p=policy||{};const cleaned=p.cleanup?.deleted||0;
 return `<div class="creative-retention-card"><span class="creative-retention-icon">↓</span><div><b>${lang==='es'?'Tus imágenes quedan guardadas aquí':'Your images stay saved here'}</b><p>${lang==='es'?`Como un droplet pequeño ya trae espacio suficiente para empezar, no borro tus creativos automáticamente. Descarga las piezas importantes y, si algún día necesitas liberar espacio, limpia solo los borradores. Las imágenes ya elegidas para anuncios se conservan.`:`A small droplet has enough storage to get started, so drafts are not deleted automatically. Download important files, and if you ever need space, clear only draft images. Images chosen for ads are preserved.`}</p><div class="creative-retention-tags"><span>${lang==='es'?`${p.temporary_image_count||0} borradores guardados`:`${p.temporary_image_count||0} saved drafts`}</span><span>${lang==='es'?`${p.saved_ad_image_count||0} piezas de anuncio protegidas`:`${p.saved_ad_image_count||0} protected ad assets`}</span>${cleaned?`<span>${lang==='es'?`${cleaned} borradores limpiados`:`${cleaned} drafts cleared`}</span>`:''}</div><div class="creative-retention-actions"><button class="btn" type="button" data-action-code="clearCreativeStorage()">${lang==='es'?'Limpiar borradores':'Clear drafts'}</button></div></div></div>`;
}
function creativeVariantMarkup(batch,variant){
 const copy=variant.copy||{};const asset=(variant.assets||[])[0];const prompts=(variant.image_prompts||[]).map(p=>p.aspect_ratio).join(' / ');
 const frame=asset?`<div class="creative-frame"><div class="creative-frame-loading">${lang==='es'?'Cargando vista previa...':'Loading preview...'}</div><img data-preview-url="${escapeHtml(asset.preview_url)}" alt="${escapeHtml(demoCreativeText(copy.headline)||'Creative preview')}" hidden><span class="creative-asset-state">${lang==='es'?'Imagen lista':'Image ready'}</span></div>`:`<div class="creative-frame"><div class="creative-concept-board"><span class="creative-angle">${escapeHtml(demoCreativeText(copy.angle)||'idea')}</span><b>${escapeHtml(demoCreativeText(copy.headline)||'Nueva idea')}</b><div class="creative-ratios">${(variant.image_prompts||[]).map(p=>`<span>${escapeHtml(p.aspect_ratio)}</span>`).join('')}</div></div><span class="creative-asset-state">${variant.generation_errors?.length?(lang==='es'?'No generada':'Not generated'):(lang==='es'?'Idea':'Idea')}</span></div>`;
 const studio=state.config?.creative_studio||{};const canRender=Boolean(studio.image_generation_ready);const productGuide=batch.brand_memory?.product?.guide||'';const adBrief=batch.brand_memory?.ad_brief?.guide||'';
 const codexPrompt=lang==='es'?`Genera una imagen final para Meta Ads usando Codex/Image a partir de esta idea: ${copy.headline||variant.variant_id}. Producto o campaña: ${batch.campaign.name}. Usa la guía de marca y, si falta algo, pregúntame una sola cosa antes de generar.`:`Generate a final Meta Ads image using Codex/Image from this idea: ${copy.headline||variant.variant_id}. Product or campaign: ${batch.campaign.name}. Use the brand guide and ask one question before generating if anything is missing.`;
 const primary=asset?`<button class="btn primary" data-action-code="stageUpload(${chatArg(batch.manifest_path)},${chatArg(variant.variant_id)},${JSON.stringify((variant.assets||[]).map(a=>a.aspect_ratio))})">${lang==='es'?'Preparar para publicar':'Prepare to publish'}</button>`:(studio.image_generation_provider==='codex_image')?`<button class="btn primary" data-action-code="openChat(${chatArg(codexPrompt)})">${lang==='es'?'Crear con Codex':'Create with Codex'}</button>`:canRender?`<button class="btn primary" data-action-code="generateRefresh(${chatArg(batch.campaign.id)},${chatArg(productGuide)},${chatArg(adBrief)})">${lang==='es'?'Crear imagen final':'Create final image'}</button>`:`<button class="btn" data-action-code="openChat(${chatArg(lang==='es'?`Convierte la idea ${copy.headline||variant.variant_id} de ${batch.campaign.name} en una imagen final para anuncios. Dime qué necesitas para generarla.`:`Turn the ${copy.headline||variant.variant_id} idea from ${batch.campaign.name} into a final ad image. Tell me what you need to generate it.`)})">${lang==='es'?'Crear imagen':'Create image'}</button>`;
 const download=asset?`<button class="btn" data-action-code="downloadCreativeAsset(${chatArg(asset.preview_url)},${chatArg(asset.filename||'creative.png')})">${lang==='es'?'Descargar':'Download'}</button>`:'';
 return `<article class="creative-variant">${frame}<div class="creative-variant-body"><span class="creative-angle">${escapeHtml(demoCreativeText(copy.angle)||variant.variant_id)}</span><h4>${escapeHtml(demoCreativeText(copy.headline)||variant.variant_id)}</h4>${asset?creativeStorageNote(asset):''}<p class="creative-copy">${escapeHtml(demoCreativeText(copy.primary_text)||'')}</p><p class="creative-cta">${escapeHtml(demoCreativeText(copy.cta)||'')} ${prompts?` · ${escapeHtml(prompts)}`:''}</p><div class="creative-actions">${primary}${download}<button class="btn ask-btn" data-action-code="openChat(${chatArg(lang==='es'?`Revisa la idea ${copy.headline||variant.variant_id} para ${batch.campaign.name}. ¿La probarías y qué cambiarías?`:`Review the ${copy.headline||variant.variant_id} idea for ${batch.campaign.name}. Would you test it and what would you change?`)})">${lang==='es'?'Preguntar':'Ask'}</button></div></div></article>`;
}
function renderCreativeStudio(){
 renderBrandGuides();
 const studio=state.config.creative_studio||{};const batches=state.creative_refreshes||[];const uploads=state.creative_uploads||[];
 const variants=batches.reduce((count,batch)=>count+(batch.variants||[]).length,0);const imageCount=batches.reduce((count,batch)=>count+(batch.variants||[]).reduce((subtotal,variant)=>subtotal+(variant.assets||[]).length,0),0);
 qs('#creative-studio-kicker').textContent=lang==='es'?'Ideas para anuncios':'Ad ideas';
 qs('#creative-studio-title').textContent=lang==='es'?'Crea tus anuncios':'Create your ads';
 qs('#creative-studio-description').textContent=lang==='es'?'Cuéntale al agente qué quieres vender y cómo quieres mostrarlo. Te ayudará a preparar imágenes y textos para tus anuncios.':'Tell the agent what you want to sell and how you want to show it. It will help prepare images and text for your ads.';
 qs('#creative-agent-cta').textContent=lang==='es'?'Crear con el agente':'Create with the agent';
 qs('#creative-refresh-cta').textContent=lang==='es'?'Mejorar un anuncio actual':'Improve an existing ad';
 qs('#creative-library-kicker').textContent=lang==='es'?'Ideas creadas':'Agent ideas';
 qs('#creative-library-title').textContent=lang==='es'?'Creativos para revisar':'Images and text to review';
 qs('#creative-upload-kicker').textContent=lang==='es'?'Antes de publicar':'Ready for Meta';
 qs('#creative-upload-title').textContent=lang==='es'?'Anuncios que puedes aprobar':'Ads you can approve';
 const renderer=studio.image_generation_provider==='codex_image'?(lang==='es'?'Codex/Image conectado para crear imágenes':'Codex/Image connected for image generation'):(studio.image_generation_ready?(lang==='es'?'Puede crear imágenes':'Image generator active'):(lang==='es'?'Conecta ChatGPT/Codex para crear imágenes reales':'Connect ChatGPT/Codex to generate real images'));
 qs('#creative-studio-pulse').innerHTML=`<div class="creative-pulse-stat"><b>${variants}</b><span>${lang==='es'?'Ideas':'Ideas'}</span></div><div class="creative-pulse-stat"><b>${imageCount}</b><span>${lang==='es'?'Imágenes listas':'Final images'}</span></div><div class="creative-pulse-stat"><b>${uploads.length}</b><span>${lang==='es'?'Por aprobar':'Staged uploads'}</span></div><p class="notice">${escapeHtml(renderer)}</p>${creativeStorageReminderMarkup(studio.asset_policy)}`;
 qs('#creative-list').innerHTML=batches.length?batches.map(batch=>`<section class="creative-batch"><div class="creative-batch-head"><div><h4>${escapeHtml(demoCreativeText(batch.campaign?.name||'Campaña'))}${batch.brand_memory?.product?.name?`<span class="creative-batch-product">${escapeHtml(batch.brand_memory.product.name)}</span>`:''}${batch.brand_memory?.ad_brief?.name?`<span class="creative-batch-product">${escapeHtml(batch.brand_memory.ad_brief.name)}</span>`:''}</h4><p class="creative-batch-meta">${creativeStatus(batch.status)} · ${new Date(batch.created_at).toLocaleString()}</p></div><span class="badge ${batch.has_generated_images?'ok':'warn'}">${batch.has_generated_images?(lang==='es'?'Vista previa':'Preview'):(lang==='es'?'Sin imagen':'No image')}</span></div><div class="creative-variants">${(batch.variants||[]).map(variant=>creativeVariantMarkup(batch,variant)).join('')}</div></section>`).join(''):`<div class="creative-empty"><div><h3>${lang==='es'?'Todavía no has creado ideas de anuncios':'No ad ideas yet'}</h3><p>${lang==='es'?'Habla con el agente sobre lo que quieres anunciar. Preparará ideas de imágenes y textos para que elijas la que más te guste.':'Talk to the agent about what you want to advertise. It will prepare image and text ideas for you to choose from.'}</p><button class="btn primary" data-action-code="openBrandMemory('ad_brief','')">${lang==='es'?'Crear una idea de anuncio':'Create an ad idea'}</button></div></div>`;
 qs('#upload-list').innerHTML=uploads.length?`<div class="creative-upload-grid">${uploads.map(upload=>`<article class="creative-upload-card"><h4>${escapeHtml(demoCreativeText(upload.campaign?.name||'Campaña'))} · ${escapeHtml(upload.variant_id||'')}</h4><span class="badge ${upload.status==='ready_for_approval'?'ok':'warn'}">${upload.status==='ready_for_approval'?(lang==='es'?'Espera tu aprobación':'In approval'):(lang==='es'?'Falta completar':'Needs work')}</span><p>${upload.status==='ready_for_approval'?(lang==='es'?'Revisa esta imagen. Solo se creará el anuncio en Meta cuando lo apruebes.':'This proposal waits for your confirmation before creating the Meta ad.'):(lang==='es'?'Completa lo que falta antes de enviarla a Meta.':'Complete missing items before sending it to Meta.')}</p>${upload.missing_requirements?.length?`<div class="creative-blockers">${upload.missing_requirements.map(item=>`· ${escapeHtml(creativeMissingText(item))}`).join('<br>')}</div>`:''}</article>`).join('')}</div>`:`<p class="notice">${lang==='es'?'Cuando prepares una imagen para publicar, aparecerá aquí para que la apruebes.':'Once you choose a finished image, preparation for approval will appear here.'}</p>`;
 hydrateCreativePreviews();
}
async function hydrateCreativePreviews(){
 const images=[...document.querySelectorAll('#creative-list img[data-preview-url]')];
 for(const image of images){
  const path=image.dataset.previewUrl;if(!path)continue;
  try{
   if(!creativePreviewUrls.has(path)){const response=await fetchProtectedFile(path);creativePreviewUrls.set(path,URL.createObjectURL(await response.blob()))}
   image.src=creativePreviewUrls.get(path);image.hidden=false;image.previousElementSibling?.remove();
  }catch(err){const loading=image.previousElementSibling;if(loading)loading.textContent=lang==='es'?'Vista previa protegida':'Protected preview'}
 }
}
async function downloadCreativeAsset(path,filename){
 try{
  const response=await fetchProtectedFile(path);
  const blob=await response.blob();
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=url;link.download=filename||'meta-ads-creative.png';
  document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  toast(lang==='es'?'Imagen descargada. Guárdala si quieres conservarla.':'Image downloaded. Keep it if you want to save it.');
 }catch(err){toast(lang==='es'?'No pude descargar esa imagen.':'Could not download that image.')}
}
function clearCreativeStorage(){
 const p=state.config?.creative_studio?.asset_policy||{};const count=p.temporary_image_count||0;
 const box=qs('#confirm-overlay');
 box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Limpiar borradores creativos':'Clear creative drafts'}</h2><p>${lang==='es'?`Esto borrará ${count} imagen${count===1?'':'es'} generada${count===1?'':'s'} que todavía no elegiste para anuncios. No borra piezas ya preparadas para publicar ni anuncios activos en Meta.`:`This deletes ${count} generated draft image${count===1?'':'s'} that you have not chosen for ads yet. It does not delete images prepared for publishing or active Meta ads.`}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" data-action-code="confirmClearCreativeStorage()">${lang==='es'?'Limpiar borradores':'Clear drafts'}</button></div></div>`;
 box.classList.add('open');
}
async function confirmClearCreativeStorage(){
 try{
  closeConfirm();
  const res=await api('/api/creative-storage/clear',{method:'POST',body:'{}'});
  toast(lang==='es'?`${res.result?.deleted||0} borrador${res.result?.deleted===1?'':'es'} limpiado${res.result?.deleted===1?'':'s'}`:`${res.result?.deleted||0} draft image${res.result?.deleted===1?'':'s'} cleared`);
  await load();
 }catch(err){toast(lang==='es'?'No pude limpiar esos borradores.':'Could not clear those drafts.')}
}
function approvalNote(p){
 if(p.type==='create_campaign'&&p.payload?.final_status==='ACTIVE')return lang==='es'?'Si apruebas, la campaña se encenderá y podrá empezar a gastar el presupuesto que elegiste.':'If you approve, the campaign will turn on and may start spending the budget you chose.';
 if(p.type==='create_campaign'||p.type==='creative_upload')return lang==='es'?'Si apruebas, quedará lista pero apagada. No mostrará anuncios ni gastará dinero hasta que decidas encenderla.':'If you approve, it will be ready but turned off. It will not show ads or spend money until you turn it on.';
 if(p.type==='pause_campaign')return lang==='es'?'Esto apagará una campaña que ya está mostrando anuncios. Revisa bien antes de aprobar.':'This will turn off a campaign that is already showing ads. Check carefully before approving.';
 return '';
}
function guardrailText(reason){
 const es={approval_required:'El agente prepara la acción y espera tu sí antes de tocar algo delicado.',budget_over_safety_limit:'El cambio de presupuesto supera tus reglas de seguridad.',resume_requires_approval:'Reactivar campañas siempre pide aprobación.',new_campaign_requires_approval:'Las campañas nuevas activas siempre pasan por aprobación.',new_campaigns_always_require_approval:'Las campañas nuevas activas siempre pasan por aprobación.',creative_requires_approval:'Publicar anuncios o creativos siempre pasa por aprobación.',pause_spend_over_limit:'La campaña ya gastó más de tu límite para pausar sin pedir permiso.'};
 const en={approval_required:'The agent prepares the action and waits for your yes before touching anything sensitive.',budget_over_safety_limit:'The budget change is above your safety rules.',resume_requires_approval:'Resuming campaigns always asks for approval.',new_campaign_requires_approval:'New active campaigns always go through approval.',new_campaigns_always_require_approval:'New active campaigns always go through approval.',creative_requires_approval:'Publishing new ads or creatives always goes through approval.',pause_spend_over_limit:'The campaign already spent more than your no-approval pause limit.'};
 return (lang==='es'?es:en)[reason]||String(reason||'');
}
function approvalMeta(p){
 const payload=p.payload||{};const requested=payload.requested||{};const type=p.type||'';
 const name=payload.name||payload.campaign_name||requested.campaign||payload.campaign_id||payload.upload_id||type;
 const created=new Date(p.created_at||Date.now()).toLocaleString();
 const base={name,created,severity:'medium',riskLabel:lang==='es'?'Revisar':'Review',title:actionName(type),requested:lang==='es'?'El agente preparó una acción para revisar.':'The agent prepared an action for review.',reason:guardrailText(payload.guardrail_reason)||approvalNote(p)||'',outcome:approvalNote(p)||'',risk:lang==='es'?'Revisa que esta acción tenga sentido antes de aprobar.':'Check that this action makes sense before approving.',facts:[]};
 if(type==='budget_change'){
  const current=payload.current_budget??payload.current??payload.recommended_budget;const next=payload.new_budget??payload.recommended_budget;const change=payload.change_pct;
  base.title=lang==='es'?'Cambiar presupuesto':'Change budget';
  base.requested=lang==='es'?`Ajustar el presupuesto diario de ${name}.`:`Adjust daily budget for ${name}.`;
  base.reason=base.reason|| (lang==='es'?'El cambio necesita tu aprobación por tus reglas.':'Your rules require approval for this change.');
  base.outcome=lang==='es'?`Pasará de ${fmtMoney(current)} a ${fmtMoney(next)} por día.`:`It will move from ${fmtMoney(current)} to ${fmtMoney(next)} per day.`;
  base.risk=lang==='es'?'Subir presupuesto puede acelerar gasto; bajarlo puede frenar aprendizaje o ventas.':'Increasing budget can accelerate spend; lowering it can slow learning or sales.';
  base.facts=[['Actual',fmtMoney(current)],['Nuevo',fmtMoney(next)]];
  if(change!==undefined)base.facts.push([lang==='es'?'Cambio':'Change',`${change}%`]);
 }else if(type==='pause_campaign'){
  base.title=lang==='es'?'Pausar campaña':'Pause campaign';base.severity='high';base.riskLabel=lang==='es'?'Alto':'High';
  base.requested=lang==='es'?`Pausar ${name}.`:`Pause ${name}.`;
  base.outcome=lang==='es'?'La campaña dejará de mostrar anuncios.':'The campaign will stop showing ads.';
  base.risk=lang==='es'?'Puede cortar gasto débil, pero también puede detener ventas si la lectura está incompleta.':'It can stop weak spend, but it can also stop sales if the read is incomplete.';
  base.facts=[[lang==='es'?'Gasto':'Spend',fmtMoney(payload.spend||0)]];
 }else if(type==='resume_campaign'){
  base.title=lang==='es'?'Reactivar campaña':'Resume campaign';base.severity='medium';base.riskLabel=lang==='es'?'Medio':'Medium';
  base.requested=lang==='es'?`Reactivar ${name}.`:`Resume ${name}.`;
  base.outcome=lang==='es'?'La campaña podrá volver a mostrar anuncios y gastar presupuesto.':'The campaign may show ads and spend budget again.';
  base.risk=lang==='es'?'Reactivar puede volver a gastar; confirma que el problema anterior ya fue corregido.':'Resuming can spend again; confirm the previous issue is fixed.';
 }else if(type==='create_campaign'){
  const active=payload.final_status==='ACTIVE';
  base.title=active?(lang==='es'?'Crear campaña activa':'Create active campaign'):(lang==='es'?'Crear campaña lista':'Create ready campaign');
  base.severity=active?'high':'medium';base.riskLabel=active?(lang==='es'?'Puede gastar':'Can spend'):(lang==='es'?'Preparada':'Prepared');
  base.requested=lang==='es'?`Crear ${name}.`:`Create ${name}.`;
  base.outcome=active?(lang==='es'?'Al aprobar, quedará activa y podrá empezar a gastar el presupuesto elegido.':'If approved, it will be active and may start spending the selected budget.'):(lang==='es'?'Al aprobar, se crea lista pero apagada. No gastará hasta que la enciendas.':'If approved, it is created ready but off. It will not spend until turned on.');
  base.risk=active?(lang==='es'?'Es una luz verde real para inversión. Revisa presupuesto, destino, imagen y mensaje.':'This is a real green light for spend. Review budget, destination, image, and message.'):(lang==='es'?'Riesgo bajo de gasto inmediato, pero revisa que la estructura esté correcta.':'Low immediate spend risk, but check that the structure is right.');
  base.facts=[[lang==='es'?'Presupuesto':'Budget',fmtMoney(requested.daily_budget||0)],[lang==='es'?'Estado final':'Final status',active?'ACTIVE':'PAUSED']];
 }else if(type==='creative_upload'){
  base.title=lang==='es'?'Publicar creativo':'Publish creative';base.severity='medium';base.riskLabel=lang==='es'?'Creativo':'Creative';
  base.requested=lang==='es'?`Preparar el anuncio ${payload.variant_id||''} para ${name}.`:`Prepare ad ${payload.variant_id||''} for ${name}.`;
  base.outcome=lang==='es'?'Creará o preparará piezas en Meta solo después de tu aprobación.':'It will create or prepare Meta assets only after approval.';
  base.risk=lang==='es'?'Revisa que imagen, texto, destino y página sean correctos antes de aprobar.':'Review image, text, destination, and Page before approving.';
  base.facts=[[lang==='es'?'Variante':'Variant',payload.variant_id||'-']];
 }
 return base;
}
function approvalAskDraft(p,meta){
 const safeName=meta.name||actionName(p.type);
 if(lang==='es')return `Explícame esta aprobación antes de que decida: ${meta.title} para ${safeName}. Quiero entender qué pidió el agente, por qué lo sugiere, qué riesgo tiene, qué pasa si apruebo y si tú lo aprobarías ahora o esperarías.`;
 return `Explain this approval before I decide: ${meta.title} for ${safeName}. I want to understand what the agent requested, why, the risk, what happens if I approve, and whether you would approve now or wait.`;
}
function approvalCard(p){
 const meta=approvalMeta(p);const riskClass=meta.severity||'medium';const facts=meta.facts||[];
 return `<article class="approval-card ${riskClass}"><div class="approval-top"><div class="approval-icon">AI</div><div class="approval-title"><b>${escapeHtml(meta.title)}</b><span>${escapeHtml(meta.name)} · ${escapeHtml(meta.created)}</span></div><span class="approval-risk ${riskClass}">${escapeHtml(meta.riskLabel)}</span></div><div class="approval-section"><b>${lang==='es'?'Qué pidió el agente':'What the agent requested'}</b><p>${escapeHtml(meta.requested)}</p></div><div class="approval-section"><b>${lang==='es'?'Por qué está esperando tu sí':'Why it is waiting for your yes'}</b><p>${escapeHtml(meta.reason|| (lang==='es'?'Tus reglas piden aprobación para esta acción.':'Your rules require approval for this action.'))}</p></div><div class="approval-section"><b>${lang==='es'?'Qué pasa si apruebas':'What happens if you approve'}</b><p>${escapeHtml(meta.outcome)}</p></div><div class="approval-section"><b>${lang==='es'?'Riesgo a revisar':'Risk to review'}</b><p>${escapeHtml(meta.risk)}</p></div>${facts.length?`<div class="approval-facts">${facts.map(([label,value])=>`<div class="approval-fact"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}</div>`:''}<div class="approval-actions"><button class="btn ask-btn" data-action-code="openChat(${chatArg(approvalAskDraft(p,meta))})">${lang==='es'?'Preguntar antes':'Ask first'}</button><button class="btn primary" data-action-code="approvePending(${chatArg(p.id)})">${t('approve')}</button></div></article>`;
}
function statusLabel(s){return s==='ok'?t('ok'):s==='blocked'?t('blocked'):t('check')}
function setupItem(key){for(const sec of state.setup.sections){const found=sec.items.find(i=>i.key===key);if(found)return found}return {status:'blocked',detail:''}}
function stepCopy(key){
	 const en={
	  title:'Initial setup',subtitle:'Connect the essentials. The deep business questions happen later through the agent.',progress:'ready',done:'Done',next:'Next',review:'Review',
	  helper:'Help',
	  website:['Paste your website and social media','If anything is missing, paste your website or socials. The agent uses them to build a first business map.',''],
	  context:['Business interview','The agent asks this later through Telegram, one question at a time.',''],
	  strategy:['First plan','The agent prepares this after the interview.',''],
	  license:['Add your license','Paste the one code you received from us.',''],
	  chatgpt:['Connect ChatGPT','Choose ChatGPT/Codex or an API model like MiniMax M3.',''],
	  telegram:['Connect Telegram','Recommended: talk to the manager from your phone. After this, choose how detailed its replies should be.',''],
	  communication:['Choose how the agent explains things','Use simple words or allow technical detail. You can change this later.',''],
	  meta:['Connect my Facebook account','Secure step: use your own Facebook/Meta connection and access key.',''],
	  account:['Pick one account','Choose the ad account this tool should help with.',''],
	  destination:['Pick where ads go','Add the Facebook Page, Instagram, website, and optional direct publishing key.',''],
	  insights:['Read real results','I check your real numbers and do not change anything yet.',''],
	  dryrun:['Review safely','The agent prepares suggestions and waits for your yes.',''],
	  approval:['Approve one change','Check one suggested change before anything real happens.',''],
	  live:['Approval protection','Admira prepares safely in pause. Activation, spending, publishing, deleting, or sensitive data waits for your approval.',''],
	  smoke:['Tiny live test later','Use this only when you are ready for a very small real change.',''],
	  password:['Create your password','Choose a password only you know.',''],
	  guide:['Quick guide','Read the short cards before entering the dashboard.','']
	 };
	 const es={
	  title:'Configuración inicial',subtitle:'Conecta lo esencial. La entrevista profunda la hace el agente después.',progress:'listo',done:'Listo',next:'Siguiente',review:'Revisar',
	  helper:'Ayuda',
	  website:['Pega tu web y redes','Si falta algo, pega tu web o redes. El agente las usa para crear un primer mapa del negocio.',''],
	  context:['Entrevista del negocio','El agente la hace después por Telegram, una pregunta a la vez.',''],
	  strategy:['Primer plan','El agente lo prepara después de la entrevista.',''],
	  license:['Pega tu licencia','Pega el único código que recibiste de nosotros.',''],
	  chatgpt:['Conecta ChatGPT','Elige ChatGPT/Codex o un modelo API como MiniMax M3.',''],
	  telegram:['Conecta Telegram','Recomendado: habla con el manager desde tu celular. Después elegirás qué tan técnicas serán sus respuestas.',''],
	  communication:['Elige cómo quieres que te explique','Usa palabras simples o permite explicaciones técnicas. Podrás cambiarlo después.',''],
	  meta:['Conectar mi cuenta de Facebook','Paso seguro: usa tu propia conexión de Facebook/Meta y tu propia clave.',''],
	  account:['Elige una cuenta','Escoge la cuenta de anuncios que quieres usar.',''],
	  destination:['Elige dónde van los anuncios','Agrega la página de Facebook, Instagram, web y la clave opcional para publicación directa.',''],
	  insights:['Lee datos reales','Miro tus números reales y todavía no cambio nada.',''],
	  dryrun:['Revisar con aprobación','El agente prepara sugerencias y espera tu sí.',''],
	  approval:['Aprueba un cambio','Revisa un cambio sugerido antes de que pase algo real.',''],
	  live:['Protección por aprobación','Admira prepara seguro en pausa. Activar, gastar, publicar, borrar o enviar datos sensibles espera tu aprobación.',''],
	  smoke:['Prueba pequeña después','Úsalo solo cuando quieras hacer un cambio real muy pequeño.',''],
	  password:['Crea tu contraseña','Elige una contraseña que solo tú conozcas.',''],
	  guide:['Guía rápida','Lee las tarjetas cortas antes de entrar al dashboard.','']
	 };
 return (lang==='es'?es:en)[key];
}
function copyCommand(value){navigator.clipboard?.writeText(value).then(()=>toast(t('copied'))).catch(()=>toast(value))}
function onboardingSteps(){
 const setup=state.setup, summary=setup.summary;
 const passwordOk=Boolean(state.config.dashboard_password_set);
 const model=state.config.agent_model||{};
 const studio=state.config.creative_studio||{};
 const brain=model.brain_provider||'nvidia_nim';
 const apiBrainOk=['openai_api','minimax','nvidia_nim','custom_api'].includes(brain)&&model.api_key_set&&Boolean(model.base_url)&&Boolean(model.model);
 const modelOk=Boolean(model.chatgpt_connected)||apiBrainOk;
 const telegram=state.config.telegram_agent||{};
	 const telegramOk=Boolean(telegram.enabled&&telegram.bot_configured&&telegram.chat_id);
 const tokenOk=setupItem('access_token').status==='ok';
 const accountOk=setupItem('ad_account').status==='ok';
 const destinationOk=setupItem('page_id').status==='ok';
 const publishingOk=Boolean(state.config.publishing?.ready);
 return [
  {id:'password',status:passwordOk?'ok':'blocked'},
  {id:'meta',status:tokenOk&&accountOk&&destinationOk&&publishingOk?'ok':'blocked'},
  {id:'chatgpt',status:modelOk?'ok':'blocked'},
  {id:'telegram',status:telegramOk?'ok':'blocked'}
 ];
	}
function renderOnboarding(){
 const doneState=state.onboarding||{};
 if(doneState.completed){
  const when=doneState.completed_at?new Date(doneState.completed_at).toLocaleString():'';
	  const pendingState=Boolean(doneState.deferred||doneState.skipped||doneState.requires_repair);
	  if(pendingState){
	   const agentInterviewReasons=new Set(['entrevista_negocio','branding_creativos','campanas_anuncios','perfil_negocio']);
	   const reasons=(doneState.deferred_reasons||doneState.repair_reasons||[]).filter(reason=>reason&&!agentInterviewReasons.has(reason));
	   if(!reasons.length){qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="next-step"><div><b>${lang==='es'?'Configuración inicial terminada':'Initial setup complete'}</b><p>${lang==='es'?'La guía inicial ya fue completada. El agente seguirá con la entrevista del negocio por Telegram.':'The initial guide is complete. The agent will continue the business interview through Telegram.'}${when?` ${when}`:''}</p></div><button class="btn" data-action-code="resetOnboarding()">${lang==='es'?'Revisar configuración inicial':'Run initial setup again'}</button></div></div>`;return}
	   const reasonLabels={licencia:lang==='es'?'licencia':'license',conexion_facebook:lang==='es'?'Facebook':'Facebook',conexion_meta:lang==='es'?'Facebook':'Facebook',cuenta_publicitaria:lang==='es'?'cuenta publicitaria':'ad account',cerebro_agente:lang==='es'?'ChatGPT':'ChatGPT',telegram:'Telegram',destinos:lang==='es'?'página y web':'Page and website',datos_reales:lang==='es'?'datos reales de Meta':'real Meta data'};
   const summary=reasons.length?reasons.slice(0,4).map(r=>reasonLabels[r]||r).join(', '):(lang==='es'?'datos reales de Meta':'real Meta data');
   qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="next-step pending-setup"><div><b>${lang==='es'?'Configuración inicial pendiente':'Initial setup still pending'}</b><p>${lang==='es'?`Entraste al dashboard para completar luego. Falta: ${summary}. Hasta terminar esto, el dashboard quedará sin datos reales y el agente no analizará campañas.`:`You opened the dashboard before finishing setup. Still missing: ${summary}. Until this is finished, the dashboard stays without real data and the agent will not analyze campaigns.`}${when?` ${when}`:''}</p></div><button class="btn primary" data-action-code="resumeOnboarding()">${lang==='es'?'Completar ahora':'Finish now'}</button></div></div>`;
   return;
  }
  qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="next-step"><div><b>${lang==='es'?'Configuración inicial terminada':'Initial setup complete'}</b><p>${lang==='es'?'La guía inicial ya fue completada en este equipo. Puedes volver a abrirla cuando necesites cambiar algo.':'The initial guide has already been completed on this device. You can open it again whenever you need to change something.'}${when?` ${when}`:''}</p></div><button class="btn" data-action-code="resetOnboarding()">${lang==='es'?'Revisar configuración inicial':'Run initial setup again'}</button></div></div>`;
  return;
 }
 const labels=stepCopy('title'); const sub=stepCopy('subtitle'); const progress=stepCopy('progress');
 const steps=onboardingSteps(); const done=steps.filter(s=>s.status==='ok').length;
 const labelFor=s=>s.status==='ok'?stepCopy('done'):(s.status==='blocked'?stepCopy('next'):stepCopy('review'));
 const next=steps.find(s=>s.status!=='ok')||steps[steps.length-1]; const nextCopy=stepCopy(next.id);
 qs('#onboarding-wizard').innerHTML=`<div class="onboarding"><div class="onboarding-head"><div><h3>${labels}</h3><p>${sub}</p></div><div class="progress"><b>${done}/${steps.length}</b><span>${progress}</span></div></div><div class="next-step"><div><b>${lang==='es'?'Siguiente':'Next'}: ${nextCopy[0]}</b><p>${nextCopy[1]}</p></div>${nextCopy[2]?`<button class="btn copy-btn" data-action-code="copyCommand(${JSON.stringify(nextCopy[2]).replaceAll('"','&quot;')})">${t('copy_command')}</button>`:''}</div><div class="step-list">${steps.map((s,i)=>{const c=stepCopy(s.id);return `<div class="setup-step ${s.status}"><div class="step-num">${i+1}</div><div class="step-main"><b>${c[0]}</b><p>${c[1]}</p>${c[2]?`<details class="helper-command"><summary>${stepCopy('helper')}</summary><span class="step-command">${c[2]}</span></details>`:''}</div><div class="step-badge">${labelFor(s)}</div></div>`}).join('')}</div><div class="mode-actions" data-style-code="margin-top:10px"><button class="btn ask-btn" data-action-code="openChat(lang==='es'?'Revisa mi configuración. Explícame el siguiente paso con palabras muy simples.':'Review my setup. Explain the next step in very simple words.')">${t('ask_agent')}</button><button class="btn primary" data-action-code="completeOnboarding()">${lang==='es'?'Terminar configuración':'Finish setup'}</button></div></div>`;
}
function onboardingFormFor(stepId){
	 const v=state.config.setup_values||{};
 if(stepId==='website')return websiteScanGuide();
 if(stepId==='context')return businessContextGuide();
 if(stepId==='strategy')return initialStrategyGuide();
	 if(stepId==='license')return `<form class="onboarding-mini two" data-submit-code="activateLicenseFromForm(event)"><label>${t('license_key')}<input name="license_key" placeholder="MAO-..." autocomplete="off"></label><label>${t('buyer_email')}<input name="license_buyer_email" value="${escapeHtml(v.license_buyer_email||'')}" placeholder="buyer@email.com" autocomplete="email"></label><div class="onboarding-step-actions"><button class="btn primary" type="submit">${t('license_activate')}</button></div></form>`;
	 if(stepId==='chatgpt')return chatGptConnectMarkup(true);
	 if(stepId==='telegram')return telegramOnboardingGuide();
 if(stepId==='meta')return metaConnectionGuide();
 if(stepId==='account')return accountPickerGuide();
 if(stepId==='destination')return destinationPickerGuide();
 if(stepId==='password')return `<form class="unlock-form" data-submit-code="setDashboardPasswordFromOnboarding(event)"><label>${t('dashboard_password')}<input id="new-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Crea una contraseña segura':'Create a secure password'}"></label><label>${lang==='es'?'Repetir contraseña':'Repeat password'}<input id="confirm-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Escríbela otra vez':'Type it again'}"></label><label><input id="new-dashboard-remember" type="checkbox" checked> ${t('remember_device')}</label><div class="unlock-error" id="dashboard-password-error"></div><button class="btn primary" type="submit">${lang==='es'?'Guardar mi contraseña':'Save my password'}</button></form>`;
	 return passiveStepGuide(stepId);
	}
function websiteScanGuide(){
 const p=state.business_profile||{};
 const v=state.config.setup_values||{};
 const meta=p.meta_assets||{};
 const website=p.website_url||v.landing_url||'';
 const socialLinks=[...(p.social_links||[])].filter(Boolean);
 const links=[website,...socialLinks].filter(Boolean).filter((item,index,arr)=>arr.indexOf(item)===index).join('\n');
 const pageId=v.page_id||meta.page_id||'';
 const pageName=meta.page_name||'';
 const igId=v.instagram_actor_id||meta.instagram_actor_id||'';
 const igName=meta.instagram_username||'';
 const foundCards=[
  {ok:Boolean(pageId),label:lang==='es'?'Página de Facebook':'Facebook Page',value:pageName||pageId,optional:false},
  {ok:Boolean(igId),label:'Instagram',value:igName||igId,optional:true},
  {ok:Boolean(website),label:lang==='es'?'Web':'Website',value:website,optional:false}
 ];
 const statusCards=foundCards.map(item=>`<div class="asset-status ${item.ok?'ok':(item.optional?'optional':'missing')}"><span>${item.ok?'✓':(item.optional?'~':'!')}</span><b>${escapeHtml(item.label)}</b><p>${escapeHtml(item.ok?item.value:(item.optional?(lang==='es'?'Opcional si no usas Instagram.':'Optional if you do not use Instagram.'):(lang==='es'?'Falta agregarlo.':'Still needed.')))}</p></div>`).join('');
 const missingText=!website
  ? (lang==='es'?'Pega abajo el link de tu web, tienda o página donde quieres enviar visitas.':'Paste below your website, store, or landing page link.')
  : (!igId?(lang==='es'?'Ya tengo tu web. Si también tienes Instagram conectado, puedes pegarlo; si no, sigue.':'I already have your website. If you also have Instagram, paste it; otherwise continue.'):(lang==='es'?'Ya tengo lo importante. Puedes agregar más links si ayudan.':'I have the important pieces. You can add more links if useful.'));
 return `<div class="setup-guide private-connection business-start-shell"><section class="guide-hero business-hero compact-business-scan"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Primer mapa del negocio':'First business map'}</span><h3>${lang==='es'?'Completa lo que falte':'Complete what is missing'}</h3><p>${lang==='es'?'Primero uso lo que Meta ya encontró. Si pegas tu web o redes públicas, el agente las lee y prepara una idea inicial de productos, servicios, nicho y público para arrancar mejor en Telegram.':'First I use what Meta already found. If you paste your website or public socials, the agent reads them and prepares an initial idea of products, services, niche, and audience before Telegram.'}</p><div class="asset-status-grid">${statusCards}</div><form class="onboarding-mini business-start-form" data-submit-code="saveBusinessLinks(event)"><label>${lang==='es'?'Web o redes que falten':'Website or socials that are missing'}<textarea name="links" rows="5" placeholder="${lang==='es'?'Pega un link por línea. Ej:\\nhttps://tumarca.com\\nhttps://instagram.com/tumarca':'Paste one link per line. Ex:\\nhttps://yourbrand.com\\nhttps://instagram.com/yourbrand'}">${escapeHtml(links)}</textarea></label><p class="notice">${escapeHtml(missingText)}</p><div class="onboarding-step-actions"><button class="btn primary" type="submit">${lang==='es'?'Guardar y estudiar links':'Save and study links'}</button><button class="btn" type="button" data-action-code="skipWebsiteScan()">${lang==='es'?'Seguir sin más links':'Continue without more links'}</button></div></form></div><aside class="guide-checklist"><b>${lang==='es'?'Qué usa el agente':'What the agent uses'}</b><ol><li>${lang==='es'?'Los datos seguros que Meta permite leer de tu página.':'Safe data Meta allows from your Page.'}</li><li>${lang==='es'?'Tu web y redes públicas, si las pegas aquí.':'Your public website and socials, if you paste them here.'}</li><li>${lang==='es'?'Después Telegram confirma lo importante contigo, una pregunta a la vez.':'Then Telegram confirms the important parts with you, one question at a time.'}</li></ol></aside></section><div id="business-scan-results" class="setup-guide">${businessProfileCard()}</div></div>`;
}
function businessQuestionValue(key,p){
 if(key==='main_offer')return p.main_offer||p.offer||'';
 if(key==='ideal_customer')return p.ideal_customer||p.audience||'';
 if(key==='sales_channel')return p.sales_channel||p.channel||'';
 if(key==='current_ads')return p.current_ads||p.ad_results||'';
 if(key==='what_to_improve')return p.what_to_improve||'';
 if(key==='success_goal')return p.success_goal||'';
 if(key==='budget_comfort')return p.budget_comfort||'';
 if(key==='brand_tone')return p.brand_tone||'';
 return p[key]||'';
}
function businessContextQuestions(){
 const p=state.business_profile||{};
 const custom=Array.isArray(p.onboarding_questions)&&p.onboarding_questions.length?p.onboarding_questions:[];
 if(custom.length){
  return custom.slice(0,6).map((q)=>({key:q.key,label:q.label,help:q.help,placeholder:q.placeholder||'',value:businessQuestionValue(q.key,p)}));
 }
 const hasWebsite=Boolean(p.website_url);
 const stageSuggestion=p.current_stage|| (hasWebsite?(lang==='es'?'Tengo una web lista y quiero un plan claro.':'I have a website ready and want a clear plan.'):'');
 const improvementSuggestion=p.what_to_improve|| (lang==='es'?'Entender qué hacer primero y no adivinar.':'Know what to do first without guessing.');
 return [
  {key:'main_offer',label:lang==='es'?'¿Qué vendes?':'What do you sell?',help:lang==='es'?'Una frase corta.':'One short sentence.',placeholder:lang==='es'?'Ej: un curso, una tienda, un servicio...':'Ex: a course, a store, a service...',value:businessQuestionValue('main_offer',p)},
  {key:'ideal_customer',label:lang==='es'?'¿Quién compra?':'Who buys?',help:lang==='es'?'La persona que más quieres atraer.':'The person you most want to attract.',placeholder:lang==='es'?'Ej: mamás, dueños de negocio, parejas...':'Ex: moms, business owners, couples...',value:businessQuestionValue('ideal_customer',p)},
  {key:'sales_channel',label:lang==='es'?'¿Dónde vendes?':'Where do you sell?',help:lang==='es'?'Web, WhatsApp, Instagram, tienda física o llamada.':'Website, WhatsApp, Instagram, store, or call.',placeholder:lang==='es'?'Ej: WhatsApp y mi web.':'Ex: WhatsApp and my website.',value:businessQuestionValue('sales_channel',p)},
  {key:'current_stage',label:lang==='es'?'¿En qué punto estás?':'Where are you now?',help:lang==='es'?'Empiezas, ya vendes o ya tienes anuncios.':'Starting, already selling, or already running ads.',placeholder:lang==='es'?'Ej: Ya vendo, pero cada compra me cuesta más.':'Ex: I already sell, but each purchase costs more.',value:stageSuggestion},
  {key:'what_to_improve',label:lang==='es'?'¿Qué quieres mejorar?':'What do you want to improve?',help:lang==='es'?'Qué te gustaría arreglar primero.':'What you want to fix first.',placeholder:lang==='es'?'Ej: bajar el costo de cada compra, entender anuncios, vender más.':'Ex: lower the cost per purchase, understand ads, sell more.',value:improvementSuggestion},
  {key:'success_goal',label:lang==='es'?'¿Cómo se ve una victoria?':'What is a win?',help:lang==='es'?'Algo claro para los próximos 30 días.':'Something clear for the next 30 days.',placeholder:lang==='es'?'Ej: vender 20 más, bajar costo, tener más leads.':'Ex: sell 20 more, lower cost, get more leads.',value:businessQuestionValue('success_goal',p)}
 ];
}
function businessContextGuide(){
 const p=state.business_profile||{};
 const questions=businessContextQuestions();
 businessContextQuestionIndex=Math.max(0,Math.min(businessContextQuestionIndex,questions.length-1));
 const q=questions[businessContextQuestionIndex];
 const sourceNote=p.agent_scan_status==='agent_enriched'
  ? (lang==='es'?'Leí tu web y dejé una sugerencia.':'I read your site and made a suggestion.')
  : (p.website_url?(lang==='es'?'Tomé tu web como guía. Puedes cambiar todo.':'I used your website as a guide. You can change anything.'):(lang==='es'?'Sin web no pasa nada. Te haré preguntas cortas.':'No website is fine. I will ask short questions.'));
 const isLast=businessContextQuestionIndex>=questions.length-1;
 const progress=`${businessContextQuestionIndex+1}/${questions.length}`;
 const draft=lang==='es'?`Ayúdame a responder esta pregunta con palabras simples: "${q.label}". Lo que tengo ahora es: "${q.value||'vacío'}". Si falta algo, hazme una sola pregunta.`:`Help me answer this question in simple words: "${q.label}". Current answer: "${q.value||'empty'}". If something is missing, ask one question.`;
 return `<div class="setup-guide private-connection business-question-shell"><section class="guide-hero business-hero compact-business-context"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Preguntas del negocio':'Business questions'}</span><h3>${lang==='es'?'Una pregunta a la vez':'One question at a time'}</h3><p>${sourceNote}</p></div><div class="business-question-progress"><b>${progress}</b><span>${lang==='es'?'pregunta':'question'}</span></div></section><form class="business-question-card" data-submit-code="saveBusinessContextQuestion(event)"><input type="hidden" name="field" value="${escapeHtml(q.key)}"><div class="business-question-label"><span>${progress}</span><h3>${escapeHtml(q.label)}</h3><p>${escapeHtml(q.help)}</p></div><textarea name="answer" rows="6" placeholder="${escapeHtml(q.placeholder)}">${escapeHtml(q.value||'')}</textarea><div class="business-question-actions"><button class="btn" type="button" data-action-code="setBusinessContextQuestionIndex(${businessContextQuestionIndex-1})" ${businessContextQuestionIndex===0?'disabled':''}>${lang==='es'?'Atrás':'Back'}</button><button class="btn ask-btn" type="button" data-action-code="openChat(${chatArg(draft)})">${lang==='es'?'Ayudarme':'Help me'}</button><button class="btn primary" type="submit">${isLast?(lang==='es'?'Guardar y crear plan':'Save and build plan'):(lang==='es'?'Guardar y seguir':'Save and continue')}</button></div></form>${businessProfileCard()}</div>`;
}
function initialStrategyGuide(){
 const p=state.business_profile||{};
 const plan=(p.initial_plan&&p.initial_plan.length?p.initial_plan:[
  lang==='es'?'Conectar mi cuenta de Facebook.':'Connect my Facebook account.',
  lang==='es'?'Hablar con el agente.':'Talk to the agent.',
  lang==='es'?'Preparar en pausa; activar solo con aprobación.':'Prepare paused; activate only with approval.'
  ]);
  const angles=p.suggested_angles||[];
 return `<div class="setup-guide private-connection"><section class="guide-hero business-hero"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Primer plan':'First plan'}</span><h3>${lang==='es'?'Esto entendí':'This is what I understood'}</h3><p>${escapeHtml(p.positioning||p.detected_title||p.offer|| (lang==='es'?'Todavía falta más contexto.':'We still need more context.'))}</p><div class="business-summary-grid"><div><b>${lang==='es'?'Tipo':'Type'}</b><span>${escapeHtml(p.business_type||'-')}</span></div><div><b>${lang==='es'?'Oferta':'Offer'}</b><span>${escapeHtml(p.main_offer||p.offer||'-')}</span></div><div><b>${lang==='es'?'Cliente':'Customer'}</b><span>${escapeHtml(p.ideal_customer||p.audience||'-')}</span></div></div></div><aside class="guide-checklist"><b>${lang==='es'?'Plan inicial':'Initial plan'}</b><ol>${plan.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ol></aside></section>${angles.length?`<div class="guide-panel"><b>${lang==='es'?'Ideas iniciales':'Initial ideas'}</b><ol>${angles.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ol></div>`:''}<div class="onboarding-step-actions"><button class="btn" type="button" data-action-code="setOnboardingFlowStep(onboardingFlowStep-1)">${lang==='es'?'Editar':'Edit'}</button><button class="btn primary" type="button" data-action-code="setOnboardingFlowStep(onboardingFlowStep+1)">${lang==='es'?'Seguir':'Continue'}</button><button class="btn ask-btn" type="button" data-action-code="openChat('${lang==='es'?'Revisa esta información de mi negocio y dime qué estrategia inicial prepararías para Meta Ads.':'Review this business profile and tell me what initial Meta Ads strategy you would prepare.'}')">${t('ask_agent')}</button></div></div>`;
}
function businessProfileCard(){
 const p=state.business_profile||{};
 const links=[p.website_url,...(p.social_links||[])].filter(Boolean).filter((item,index,arr)=>arr.indexOf(item)===index);
 if(!links.length&&!p.business_type&&!p.telegram_onboarding_requested_at)return '';
 const scan=p.agent_scan_status==='agent_enriched'
  ? (lang==='es'?'El agente ya hizo una primera lectura de esos links.':'The agent already made a first read of those links.')
  : (p.agent_scan_status==='agent_not_connected'||p.agent_scan_status==='agent_scan_unavailable'
   ? (lang==='es'?'Guardé los links. Cuando el agente esté conectado, los usará como contexto.':'I saved the links. When the agent is connected, it will use them as context.')
   : (lang==='es'?'Queda guardado para la entrevista por Telegram.':'Saved for the Telegram interview.'));
 return `<div class="guide-card"><b>${lang==='es'?'Contexto inicial guardado':'Initial context saved'}</b><p>${escapeHtml(p.business_type||links[0]||'')}${links.length?` · ${links.length} ${lang==='es'?'link(s)':'link(s)'}`:''}${p.scan_error?` · ${lang==='es'?'No pude leer toda la web, pero guardé el link y puedes seguir.':'I could not read the full site, but saved the link and you can continue.'}`:''}</p>${p.main_offer||p.offer?`<p>${lang==='es'?'Oferta detectada':'Detected offer'}: ${escapeHtml(p.main_offer||p.offer)}</p>`:''}<p class="notice">${escapeHtml(scan)}</p></div>`;
}
function businessSnapshotData(){
 const p=state.business_profile||{};
 const s=state.business_snapshot||state.brief?.business_context||{};
 return {
  ready:Boolean(s.ready||p.business_type||p.main_offer||p.offer||p.ideal_customer||p.audience||p.website_url),
  business_type:s.business_type||p.business_type||p.business_short||'',
  main_offer:s.main_offer||p.main_offer||p.offer||p.detected_title||'',
  ideal_customer:s.ideal_customer||p.ideal_customer||p.audience||'',
  current_stage:s.current_stage||p.current_stage||'',
  what_to_improve:s.what_to_improve||p.what_to_improve||'',
  success_goal:s.success_goal||p.success_goal||'',
  sales_channel:s.sales_channel||p.sales_channel||p.channel||'',
  brand_tone:s.brand_tone||p.brand_tone||'',
  website_url:s.website_url||p.website_url||'',
  next_step:s.next_step||'',
  audience_hint:s.audience_hint||'',
  creative_hint:s.creative_hint||'',
  campaign_hint:s.campaign_hint||'',
  summary:s.summary||''
 };
}
function businessProfileFallbacks(d){
 const es=lang==='es';
 return {
  title:d.business_type||d.main_offer||(es?'Negocio por definir':'Business to define'),
  summary:d.summary||[d.main_offer,d.ideal_customer,d.current_stage].filter(Boolean).join(' · ')||(es?'Cuéntame qué vendes y a quién ayudas.':'Tell me what you sell and who you help.'),
  offer:d.main_offer||(es?'Falta decir qué vendes':'Need what you sell'),
  customer:d.ideal_customer||(es?'Falta decir quién compra':'Need who buys'),
  stage:d.current_stage||(es?'Falta decir en qué punto estás':'Need current stage'),
  improve:d.what_to_improve||(es?'Falta elegir qué mejorar primero':'Need first improvement target'),
  next:d.next_step||(es?'Completar oferta, cliente y objetivo.':'Complete offer, customer, and goal.'),
  audience:d.audience_hint||(es?'Empezar amplio y ajustar con datos reales.':'Start broad and refine with real data.'),
  creative:d.creative_hint||(es?'Imagen clara, beneficio directo y poco texto.':'Clear image, direct benefit, little text.'),
  campaign:d.campaign_hint||(es?'Campaña simple, visible y fácil de medir.':'Simple, visible, easy-to-measure campaign.')
 };
}
function businessProfileChatPrompt(){
 const d=businessSnapshotData();
 if(!d.ready)return lang==='es'?'Quiero contarte mi negocio para que personalices el dashboard. Hazme preguntas fáciles, una por una.':'I want to tell you about my business so you can personalize the dashboard. Ask me simple questions one at a time.';
 const c=businessProfileFallbacks(d);
 return lang==='es'?`Revisa mi perfil de negocio y dime qué harías hoy. Negocio: ${c.title}. Oferta: ${c.offer}. Cliente: ${c.customer}. Quiero mejorar: ${c.improve}. Dime el siguiente paso, una audiencia inicial y una idea de creativo.`:`Review my business profile and tell me what you would do today. Business: ${c.title}. Offer: ${c.offer}. Customer: ${c.customer}. I want to improve: ${c.improve}. Give me the next step, an initial audience, and one creative idea.`;
}
function businessMini(label,value){return `<div class="business-profile-mini"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`}
function renderBusinessProfilePanel(){
 const title=qs('#business-profile-title');if(title)title.textContent=lang==='es'?'Perfil del negocio':'Business profile';
 const box=qs('#business-profile-panel');if(!box)return;
 const d=businessSnapshotData();
 if(!d.ready){
  box.innerHTML=`<div class="business-profile-empty"><p>${lang==='es'?'Todavía no sé suficiente del negocio. Cuéntame qué vendes para que el brief, los creativos y las audiencias tengan contexto real.':'I do not know enough about the business yet. Tell me what you sell so the brief, creatives, and audiences have real context.'}</p><button class="btn primary ask-btn" data-action-code="openChat(${chatArg(businessProfileChatPrompt())})">${lang==='es'?'Contarle al agente':'Tell the agent'}</button></div>`;
  return;
 }
 const c=businessProfileFallbacks(d);
 const pills=[
  d.website_url?[lang==='es'?'Web':'Website',d.website_url]:null,
  d.sales_channel?[lang==='es'?'Venta':'Sales',d.sales_channel]:null,
  d.success_goal?[lang==='es'?'Meta':'Goal',d.success_goal]:null,
  d.brand_tone?[lang==='es'?'Tono':'Tone',d.brand_tone]:null
 ].filter(Boolean);
 box.innerHTML=`<div class="business-profile-panel"><div class="business-profile-hero"><h3>${escapeHtml(c.title)}</h3><p>${escapeHtml(c.summary)}</p>${pills.length?`<div class="business-profile-pills">${pills.map(([label,value])=>`<span class="business-profile-pill">${escapeHtml(label)}: ${escapeHtml(value)}</span>`).join('')}</div>`:''}</div><div class="business-profile-grid">${businessMini(lang==='es'?'Oferta':'Offer',c.offer)}${businessMini(lang==='es'?'Cliente':'Customer',c.customer)}${businessMini(lang==='es'?'Siguiente paso':'Next step',c.next)}${businessMini(lang==='es'?'Creativo':'Creative',c.creative)}</div><div class="business-profile-grid">${businessMini(lang==='es'?'Audiencia':'Audience',c.audience)}${businessMini(lang==='es'?'Campaña':'Campaign',c.campaign)}</div><div class="business-profile-actions"><button class="btn primary ask-btn" data-action-code="openChat(${chatArg(businessProfileChatPrompt())})">${lang==='es'?'Preguntar qué haría':'Ask what to do'}</button><button class="btn" data-action-code="openChat(${chatArg(lang==='es'?'Quiero corregir o completar mi perfil de negocio. Hazme una pregunta simple a la vez.':'I want to correct or complete my business profile. Ask me one simple question at a time.')})">${lang==='es'?'Ajustar perfil':'Adjust profile'}</button></div></div>`;
}
function passiveStepGuide(stepId){
 const es={
  insights:['Leer sin tocar','El agente lee datos reales y no cambia anuncios.','Cuando conectes Meta, este paso se valida con datos reales.'],
  dryrun:['Revisar con ayuda','El resumen diario usa datos reales y prepara ideas sin tocar dinero.','Puedes actualizarlo desde Lectura diaria o desde el chat.'],
  approval:['Pedir tu sí','Los cambios importantes esperan tu aprobación.','Revisa Aprobaciones para ver las solicitudes pendientes.'],
  live:['Protección por aprobación','El agente lee datos reales y prepara acciones. Crear en pausa está permitido; activar, gastar, publicar o borrar espera tu sí.','Entra al dashboard y revisa las aprobaciones cuando quieras dar luz verde.'],
  smoke:['Prueba pequeña','Solo cuando quieras probar un cambio real muy pequeño.','No hace falta para entrar al dashboard.']
 };
 const en={
  insights:['Read only','The agent reads real data and does not change ads.','Once Meta is connected, this step checks real results.'],
  dryrun:['Review with help','The daily brief uses real data and prepares ideas without spending money.','You can refresh it from Daily Brief or ask chat.'],
  approval:['Ask for your yes','Important changes wait for your approval.','Check Approvals for pending requests.'],
  live:['Approval protection','The agent reads real data and prepares actions. Paused creation is allowed; activating, spending, publishing, or deleting waits for your yes.','Enter the dashboard and review approvals when you want to give the green light.'],
  smoke:['Tiny test','Only when you want to try a very small real change.','You do not need this to enter the dashboard.']
 };
 if(stepId==='guide')return usageCheatSheetMarkup(true);
 const copy=(lang==='es'?es:en)[stepId]||[stepCopy(stepId)[0],stepCopy(stepId)[1],lang==='es'?'Usa Siguiente cuando estes listo.':'Use Next when you are ready.'];
 return `<div class="passive-guide"><div class="passive-card"><span class="passive-state">${lang==='es'?'Paso de revisión':'Review step'}</span><b>${copy[0]}</b><p>${copy[1]}</p></div><div class="passive-side"><b>${lang==='es'?'Qué hacer ahora':'What to do now'}</b><p>${copy[2]}</p></div></div>`;
}
let metaGuideSlide=0;
let metaGuideFrame=0;
let metaGuideFrameTimer=null;
function metaFrame(src,label=''){return {src,label}}
function metaTokenSlides(){
 const appsUrl='https://business.facebook.com/latest/settings/apps';
 const usersUrl='https://business.facebook.com/latest/settings/system-users';
 const es=[
  {title:'Empieza en Meta Business',shot:'Paso 1',images:[metaFrame('tutorial-meta/meta-business-01-open-apps-menu.png','Abre Cuentas > Apps'),metaFrame('tutorial-meta/meta-business-02-add-app.png','Toca Add para crear la app')],body:'Abre Configuración del negocio y entra a Cuentas > Apps. Así Meta usa el negocio correcto desde el inicio.',items:['Esta ruta evita elegir el negocio equivocado después.','Si ya aparece una app de Admira IA para este negocio, puedes usarla.','Si no aparece, toca Add.'],actions:[{label:'Abrir Business > Apps',href:appsUrl,primary:true}]},
  {title:'Crea una app nueva',shot:'Paso 2',images:[metaFrame('tutorial-meta/meta-business-03-create-new-app-id.png','Elige Create a new app ID'),metaFrame('tutorial-meta/meta-business-04-app-details.png','Pon un nombre simple y sigue')],body:'Elige crear una app nueva y ponle un nombre fácil de reconocer.',items:['Ejemplo: Admira IA o Agente de Ads.','Usa el correo que revisas.','Después toca Next.']},
  {title:'Marca los casos de uso',shot:'Paso 3',images:[metaFrame('tutorial-meta/meta-business-05-use-cases-all.png','Cambia a All para ver más opciones'),metaFrame('tutorial-meta/meta-business-06-marketing-api-permissions.png','Marca las opciones de Marketing API'),metaFrame('tutorial-meta/meta-business-07-page-api-use-case.png','Marca Manage everything on your Page')],body:'Selecciona los permisos para anuncios y página. Eso permite leer campañas, crear anuncios y conectar la página.',items:['Marca Create & manage ads with Marketing API.','Marca Measure ad performance data with Marketing API.','Baja y marca Manage everything on your Page.']},
  {title:'Confirma el negocio y crea la app',shot:'Paso 4',images:[metaFrame('tutorial-meta/meta-business-08-select-business.png','Elige el negocio correcto'),metaFrame('tutorial-meta/meta-business-09-requirements-next.png','Si no hay requisitos, toca Next'),metaFrame('tutorial-meta/meta-business-10-create-app-final.png','Toca Create app')],body:'Revisa que el negocio sea el correcto y termina la creación de la app.',items:['No cambies nada en Requirements si Meta dice que no hay requisitos.','En Overview, confirma que todo se ve bien.','Toca Create app.']},
  {title:'Vuelve a Business y abre Usuarios del sistema',shot:'Paso 5',images:[metaFrame('tutorial-meta/meta-business-11-return-and-refresh.png','Regresa a la pestaña de Business y recarga'),metaFrame('tutorial-meta/meta-business-12-open-system-users.png','Entra a System users')],body:'Después de crear la app, vuelve a Meta Business. Desde ahí crearás la llave estable.',items:['Recarga si la app no aparece todavía.','En el menú izquierdo entra a Users > System users.'],actions:[{label:'Abrir System users',href:usersUrl,primary:true}]},
  {title:'Crea el Usuario del sistema',shot:'Paso 6',images:[metaFrame('tutorial-meta/meta-business-13-add-system-user.png','Toca Add'),metaFrame('tutorial-meta/meta-business-14-system-user-admin.png','Cambia el rol a Admin'),metaFrame('tutorial-meta/meta-business-15-create-system-user.png','Crea el usuario'),metaFrame('tutorial-meta/meta-business-16-accept-policy.png','Acepta la política si aparece')],body:'El Usuario del sistema es el dueño de la clave estable. Créalo con rol Admin para este negocio.',items:['Ponle un nombre fácil, como Admira IA.','Selecciona Admin.','Si Meta muestra la política de anuncios, acepta para continuar.']},
  {title:'Asigna activos al Usuario del sistema',shot:'Paso 7',images:[metaFrame('tutorial-meta/meta-business-17-system-user-created.png','Toca Assign assets'),metaFrame('tutorial-meta/meta-business-18-assign-page.png','Selecciona tu página de Facebook'),metaFrame('tutorial-meta/meta-business-19-assign-ad-account.png','Selecciona tu cuenta publicitaria'),metaFrame('tutorial-meta/meta-business-20-assign-app.png','Selecciona la app de Admira IA'),metaFrame('tutorial-meta/meta-business-21-assign-instagram.png','Instagram es opcional si no aparece'),metaFrame('tutorial-meta/meta-business-22-assets-assigned.png','Termina con Done')],body:'Dale acceso al Usuario del sistema a la página, cuenta publicitaria, app e Instagram si existe.',items:['Página: activa acceso para contenido, mensajes, comunidad, anuncios e insights.','Cuenta publicitaria: activa Manage ad accounts.','App: activa Manage app. Instagram: selecciónalo solo si aparece conectado.']},
  {title:'Genera la clave estable',shot:'Paso 8',images:[metaFrame('tutorial-meta/meta-business-23-generate-token.png','Toca Generate token'),metaFrame('tutorial-meta/meta-business-24-select-app-token.png','Elige la app de Admira IA'),metaFrame('tutorial-meta/meta-business-25-token-never-expire.png','Elige Never')],body:'Ahora genera la clave que Admira usará para hablar con tu propia cuenta de Meta.',items:['Elige la app que acabas de crear.','En expiración, selecciona Never.','Así no tendrás que renovar cada 60 días.']},
  {title:'Marca permisos de la clave',shot:'Paso 9',images:[metaFrame('tutorial-meta/meta-business-26-token-permissions-top.png','Marca anuncios y negocio'),metaFrame('tutorial-meta/meta-business-27-token-permissions-middle.png','Marca permisos de página'),metaFrame('tutorial-meta/meta-business-28-token-permissions-page.png','Opcional: permitir postear desde Telegram')],body:'Marca los permisos que permiten leer, crear y administrar anuncios desde tu propia conexión.',items:['Necesarios: ads_management, ads_read, business_management y pages_manage_ads.','También marca pages_show_list y pages_read_engagement.','pages_manage_posts es opcional si quieres permitir publicaciones desde Telegram.']},
  {title:'Copia la clave',shot:'Paso 10',images:[metaFrame('tutorial-meta/meta-business-29-copy-token.png','Toca Copy')],body:'Meta mostrará una clave larga una sola vez. Cópiala completa.',items:['No la compartas por chat ni correo.','Pégala solo en Admira IA, dentro de tu instalación.','Si la pierdes, puedes generar otra.']},
  {title:'Pega la clave en Admira',shot:'Paso 11',images:[metaFrame('tutorial-meta/meta-business-30-paste-token-empty.png','Pega la clave completa'),metaFrame('tutorial-meta/meta-business-31-paste-token-active.png','Admira la guarda automáticamente'),metaFrame('tutorial-meta/meta-business-32-token-saved.png','Luego buscará tus cuentas')],body:'Pega aquí la clave completa que Meta te muestra. Admira buscará tus cuentas automáticamente.',items:['La clave queda guardada solo en esta instalación.','Nosotros no la vemos.','Si no aparecen cuentas, normalmente falta asignar activos al Usuario del sistema.']}
 ];
 const en=[
  {title:'Start in Meta Business',shot:'Step 1',images:es[0].images,body:'Open Business Settings and go to Accounts > Apps so Meta starts from the right business.',items:['This avoids choosing the wrong business later.','If an Admira IA app already exists for this business, you can use it.','Otherwise click Add.'],actions:[{label:'Open Business > Apps',href:appsUrl,primary:true}]},
  {title:'Create a new app',shot:'Step 2',images:es[1].images,body:'Create a new app and give it an easy name.',items:['Example: Admira IA or Ads Agent.','Use an email you check.','Then click Next.']},
  {title:'Select use cases',shot:'Step 3',images:es[2].images,body:'Select the ad and Page use cases so the agent can read campaigns, create ads, and connect the Page.',items:['Select Create & manage ads with Marketing API.','Select Measure ad performance data with Marketing API.','Scroll and select Manage everything on your Page.']},
  {title:'Confirm the business and create the app',shot:'Step 4',images:es[3].images,body:'Confirm the correct business and finish creating the app.',items:['Do not change Requirements if Meta says there are none.','In Overview, check that everything looks right.','Click Create app.']},
  {title:'Return to Business and open System users',shot:'Step 5',images:es[4].images,body:'After creating the app, return to Meta Business. This is where you create the stable key owner.',items:['Refresh if the app does not appear yet.','Open Users > System users.'],actions:[{label:'Open System users',href:usersUrl,primary:true}]},
  {title:'Create the System User',shot:'Step 6',images:es[5].images,body:'The System User owns the stable key. Create it with Admin role for this business.',items:['Use an easy name, like Admira IA.','Choose Admin.','If Meta shows the ad policy, accept it to continue.']},
  {title:'Assign assets to the System User',shot:'Step 7',images:es[6].images,body:'Give the System User access to the Page, ad account, app, and Instagram if it exists.',items:['Page: enable content, messages, community, ads, and insights.','Ad account: enable Manage ad accounts.','App: enable Manage app. Instagram is optional if it appears.']},
  {title:'Generate the stable key',shot:'Step 8',images:es[7].images,body:'Now generate the key Admira uses to talk to your own Meta account.',items:['Choose the app you just created.','For expiration, choose Never.','That way you do not renew every 60 days.']},
  {title:'Select token permissions',shot:'Step 9',images:es[8].images,body:'Select the permissions that allow reading, creating, and managing ads through your own connection.',items:['Required: ads_management, ads_read, business_management, and pages_manage_ads.','Also select pages_show_list and pages_read_engagement.','pages_manage_posts is optional if you want posting from Telegram.']},
  {title:'Copy the key',shot:'Step 10',images:es[9].images,body:'Meta shows the long key only once. Copy it fully.',items:['Do not share it by chat or email.','Paste it only inside your Admira IA install.','If you lose it, generate a new one.']},
  {title:'Paste the key in Admira',shot:'Step 11',images:es[10].images,body:'Paste the full key Meta shows you. Admira will find your accounts automatically.',items:['The key stays only in this install.','We do not see it.','If no accounts appear, the System User usually needs asset access.']}
 ];
 return lang==='es'?es:en;
}
function renderMetaTokenSlide(){
 const slides=metaTokenSlides();const total=slides.length;metaGuideSlide=Math.max(0,Math.min(metaGuideSlide,total-1));const s=slides[metaGuideSlide];
 const frames=(Array.isArray(s.images)&&s.images.length?s.images:(s.image?[metaFrame(s.image,s.shot)]:[]));
 metaGuideFrame=frames.length?Math.max(0,Math.min(metaGuideFrame,frames.length-1)):0;
 const frame=frames[metaGuideFrame]||null;
 const isLast=metaGuideSlide===total-1;
 const nextAction=isLast?"showMetaTokenBox('stable')":`setMetaGuideSlide(${metaGuideSlide+1})`;
 const zoomLabel=lang==='es'?'Clic para ampliar':'Click to enlarge';
 const imageMarkup=frame?`<button class="meta-shot-button" type="button" aria-label="${escapeHtml(`${zoomLabel}: ${frame.label||s.title}`)}" data-action-code="openMetaScreenshot(${chatArg(frame.src)},${chatArg(frame.label||s.title)})"><img src="${metaAssetSrc(frame.src)}" alt="${escapeHtml(frame.label||s.title)}" loading="lazy"><span class="meta-zoom-hint">${zoomLabel}</span></button>${frames.length>1?`<div class="meta-frame-caption"><span>${metaGuideFrame+1}/${frames.length}</span><b>${escapeHtml(frame.label||s.shot)}</b></div>`:''}`:`<div><span>${escapeHtml(s.shot)}</span><p>${lang==='es'?'Aquí irá la captura real de este paso.':'The real screenshot for this step will go here.'}</p></div>`;
 const slideActions=(s.actions||[]).map(action=>`<a class="btn ${action.primary?'primary':''}" href="${escapeHtml(action.href)}" target="_blank" rel="noopener" ${action.code?`data-action-code="${escapeHtml(action.code)}"`:''}>${escapeHtml(action.label)}</a>`).join('');
 const frameDots=frames.length>1?`<div class="meta-frame-dots">${frames.map((item,i)=>`<button class="${i===metaGuideFrame?'active':''}" type="button" aria-label="${escapeHtml(item.label||`${s.shot} ${i+1}`)}" data-action-code="setMetaGuideFrame(${i})"></button>`).join('')}</div>`:'';
 return `<div class="meta-token-slider"><div class="meta-slide-copy"><span class="meta-slide-count">${lang==='es'?'Paso':'Step'} ${metaGuideSlide+1}/${total}</span><h4>${escapeHtml(s.title)}</h4><p>${escapeHtml(s.body)}</p><ul>${s.items.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>${slideActions?`<div class="meta-slide-actions">${slideActions}</div>`:''}<div class="meta-slider-controls"><button class="btn" type="button" data-action-code="setMetaGuideSlide(${metaGuideSlide-1})" ${metaGuideSlide===0?'disabled':''}>${lang==='es'?'Anterior':'Back'}</button><button class="btn ${isLast?'primary':''}" type="button" data-action-code="${nextAction}">${isLast?(lang==='es'?'Pegar clave':'Paste key'):(lang==='es'?'Siguiente':'Next')}</button><div class="meta-slider-dots">${slides.map((_,i)=>`<button class="${i===metaGuideSlide?'active':''}" type="button" aria-label="${lang==='es'?'Ver paso':'View step'} ${i+1}" data-action-code="setMetaGuideSlide(${i})"></button>`).join('')}</div></div>${frameDots}</div><div class="meta-slide-shot ${frame?'has-frame':'missing'}">${imageMarkup}</div></div>`;
}
function metaAssetSrc(path){return `/assets/${String(path||'').split('/').map(encodeURIComponent).join('/')}`}
function openMetaScreenshot(src,label=''){
 const box=qs('#confirm-overlay');if(!box)return;
 const title=label||((lang==='es')?'Captura del paso':'Step screenshot');
 box.innerHTML=`<div class="confirm-card meta-lightbox-card"><div class="meta-lightbox-head"><div><h2>${lang==='es'?'Captura ampliada':'Expanded screenshot'}</h2><p>${escapeHtml(title)}</p></div><button class="btn chat-close" type="button" aria-label="${lang==='es'?'Cerrar captura':'Close screenshot'}" data-action-code="closeConfirm()">×</button></div><div class="meta-lightbox-frame"><img src="${metaAssetSrc(src)}" alt="${escapeHtml(title)}"></div></div>`;
 box.classList.add('open');
}
function stopMetaFrameCycle(){if(metaGuideFrameTimer){clearInterval(metaGuideFrameTimer);metaGuideFrameTimer=null}}
function startMetaFrameCycle(){
 stopMetaFrameCycle();
 const box=qs('#meta-token-slider');if(!box)return;
 const slide=metaTokenSlides()[metaGuideSlide]||{};
 const frames=Array.isArray(slide.images)&&slide.images.length?slide.images:(slide.image?[metaFrame(slide.image,slide.shot)]:[]);
 if(frames.length<2)return;
 metaGuideFrameTimer=setInterval(()=>{const current=metaTokenSlides()[metaGuideSlide]||{};const currentFrames=Array.isArray(current.images)&&current.images.length?current.images:(current.image?[metaFrame(current.image,current.shot)]:[]);if(!qs('#meta-token-slider')||currentFrames.length<2){stopMetaFrameCycle();return}metaGuideFrame=(metaGuideFrame+1)%currentFrames.length;qs('#meta-token-slider').innerHTML=renderMetaTokenSlide()},3600);
}
function maybeStartMetaFrameCycle(stepId){if(stepId==='meta')setTimeout(startMetaFrameCycle,80);else stopMetaFrameCycle()}
function setMetaGuideFrame(index){const slide=metaTokenSlides()[metaGuideSlide]||{};const frames=Array.isArray(slide.images)&&slide.images.length?slide.images:(slide.image?[metaFrame(slide.image,slide.shot)]:[]);metaGuideFrame=Math.max(0,Math.min(Number(index)||0,Math.max(0,frames.length-1)));const box=qs('#meta-token-slider');if(box)box.innerHTML=renderMetaTokenSlide();startMetaFrameCycle()}
function setMetaGuideSlide(index){metaGuideSlide=Math.max(0,Math.min(Number(index)||0,metaTokenSlides().length-1));metaGuideFrame=0;const box=qs('#meta-token-slider');if(box)box.innerHTML=renderMetaTokenSlide();startMetaFrameCycle()}
function metaConnectionGuide(){
 const v=state.config.setup_values||{};
 const tokenLabel=lang==='es'?'Clave de Facebook/Meta':'Facebook/Meta key';
 const tokenPlaceholder=lang==='es'?'Pega aquí la clave completa que Meta te mostró':'Paste the full key Meta showed you';
 const tokenNotice=lang==='es'?'Se guarda automáticamente al pegarla. Nosotros no recibimos esta clave; queda local en esta instalación. Puedes cambiarla después desde Configuración.':'It saves automatically when pasted. We do not receive this key; it stays local to this install. You can change it later from Setup.';
 if(lang==='es')return `<div class="setup-guide private-connection meta-token-walkthrough"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Paso seguro</span><h3>Crea tu app privada en Meta</h3><p>En este paso vas a crear una app en Meta. Esa app sirve como puente privado entre tu cuenta de Facebook/Meta y tu agente de IA. Es personal para tu negocio, queda bajo tu control y es más segura que conectar tu cuenta a una plataforma externa.</p><div class="guide-actions"><button class="btn" type="button" data-action-code="showMetaTokenBox('stable')">Ya tengo la clave</button></div></div><aside class="guide-checklist"><b>Lo que necesitas</b><ol><li>Ser administrador del negocio en Meta.</li><li>Una cuenta publicitaria real.</li><li>La página de Facebook de tu negocio.</li><li>Una app de Meta conectada al negocio.</li></ol></aside></section><div id="meta-token-slider">${renderMetaTokenSlide()}</div><div id="meta-token-box" class="token-box"><label>${tokenLabel}<textarea id="meta-token-input" data-input-code="scheduleMetaTokenAutoSave()" data-paste-code="setTimeout(scheduleMetaTokenAutoSave,0)" placeholder="${tokenPlaceholder}"></textarea></label><button class="btn" type="button" data-action-code="saveMetaToken()">Reintentar guardar</button><p class="notice">${tokenNotice}</p></div><div id="social-account-results" class="setup-guide"></div><div class="guide-panel"><b>Por qué esto es más seguro</b><p>La conexión queda entre tu cuenta de Meta y tu instalación local. Si algún día quieres cortar acceso, eliminas esa clave desde Meta y listo.</p></div></div>`;
 return `<div class="setup-guide private-connection meta-token-walkthrough"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Secure step</span><h3>Create your private Meta app</h3><p>In this step you will create a Meta app. That app works as a private bridge between your Facebook/Meta account and your AI agent. It is personal to your business, stays under your control, and is safer than connecting your account to an external platform.</p><div class="guide-actions"><button class="btn" type="button" data-action-code="showMetaTokenBox('stable')">I have the key</button></div></div><aside class="guide-checklist"><b>What you need</b><ol><li>Admin access to the Meta business.</li><li>A real ad account.</li><li>Your business Facebook Page.</li><li>A Meta app connected to the business.</li></ol></aside></section><div id="meta-token-slider">${renderMetaTokenSlide()}</div><div id="meta-token-box" class="token-box"><label>${tokenLabel}<textarea id="meta-token-input" data-input-code="scheduleMetaTokenAutoSave()" data-paste-code="setTimeout(scheduleMetaTokenAutoSave,0)" placeholder="${tokenPlaceholder}"></textarea></label><button class="btn" type="button" data-action-code="saveMetaToken()">Retry save</button><p class="notice">${tokenNotice}</p></div><div id="social-account-results" class="setup-guide"></div><div class="guide-panel"><b>Why this is safer</b><p>The connection stays between your Meta account and your local install. If you ever want to cut access, revoke that key from Meta.</p></div></div>`;
}
function accountPickerGuide(){
 const v=state.config.setup_values||{};
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Cuenta publicitaria</span><h3>Elige una cuenta y seguimos solos</h3><p>Despues de tocar <strong>Usar esta cuenta</strong>, la guia guarda la cuenta y avanza al siguiente paso automaticamente.</p><div class="guide-actions"><button class="btn primary" type="button" data-action-code="refreshSocialAccounts()">Buscar mis cuentas</button><button class="btn" type="button" data-action-code="openChat('Ayudame a elegir la cuenta publicitaria correcta con palabras simples.')">${t('ask_agent')}</button></div></div><aside class="guide-checklist"><b>Que debes elegir</b><ol><li>La cuenta donde estan tus campanas reales.</li><li>La cuenta donde tienes permiso para administrar anuncios.</li><li>Si solo aparece una, normalmente esa es la correcta.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><details class="fallback-details"><summary>Solo si no aparecen tus cuentas</summary><form class="manual-account onboarding-mini" data-submit-code="saveOnboardingSetupConfig(event)"><b>Pegar ID manualmente</b><p>Usa esto solo si el buscador de cuentas no funciona. Se ve asi: <strong>act_123456789</strong>.</p><label>${t('ad_account_id')}<input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Ad account</span><h3>Choose one account and we continue automatically</h3><p>After you click <strong>Use this account</strong>, the guide saves the account and moves to the next step by itself.</p><div class="guide-actions"><button class="btn primary" type="button" data-action-code="refreshSocialAccounts()">Find my accounts</button><button class="btn" type="button" data-action-code="openChat('Help me choose the right ad account in simple words.')">${t('ask_agent')}</button></div></div><aside class="guide-checklist"><b>What to choose</b><ol><li>The account with your real campaigns.</li><li>The account where you can manage ads.</li><li>If only one appears, it is usually the right one.</li></ol></aside></section><div id="social-account-results" class="setup-guide"></div><details class="fallback-details"><summary>Only if your accounts do not appear</summary><form class="manual-account onboarding-mini" data-submit-code="saveOnboardingSetupConfig(event)"><b>Paste ID manually</b><p>Use this only if account search does not work. It looks like <strong>act_123456789</strong>.</p><label>${t('ad_account_id')}<input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details></div>`;
}
function destinationPickerGuide(){
 const v=state.config.setup_values||{};
 const current=[v.page_id?`${lang==='es'?'Pagina':'Page'}: ${escapeHtml(v.page_id)}`:'',v.instagram_actor_id?`Instagram: ${escapeHtml(v.instagram_actor_id)}`:'',v.landing_url?`${lang==='es'?'Web':'Website'}: ${escapeHtml(v.landing_url)}`:''].filter(Boolean).join(' · ');
 const publishingGuide=directPublishingGuide(true);
 if(lang==='es')return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Destino de anuncios</span><h3>Busquemos tus páginas automáticamente</h3><p>Con la clave de Meta que ya pegaste, el dashboard intenta traer tus páginas de Facebook, el Instagram conectado y la web. Normalmente solo eliges la página correcta y seguimos.</p><div class="guide-actions"><button class="btn primary" type="button" data-action-code="discoverMetaAssets('${escapeHtml(v.ad_account_id||'')}')">Buscar páginas e Instagram</button><button class="btn" type="button" data-action-code="openChat('Ayúdame a escoger la página de Facebook correcta para mis anuncios.')">${t('ask_agent')}</button></div>${current?`<p class="notice">Guardado ahora: ${current}</p>`:''}</div><aside class="guide-checklist"><b>Qué estamos buscando</b><ol><li>Tu página de Facebook para publicar los anuncios.</li><li>Tu Instagram conectado, si existe.</li><li>El link de tu web para enviar visitas.</li></ol></aside></section><div id="destination-discovery-results" class="setup-guide"></div><details class="fallback-details"><summary>Solo si no aparece tu página</summary><form class="manual-account onboarding-mini two" data-submit-code="saveOnboardingSetupConfig(event)"><b>Escribir datos manualmente</b><p>Usa esto solo si Meta no devuelve tus páginas. El agente también puede ayudarte por chat a encontrarlas.</p><label>${t('page_id')}<input name="page_id" value="${escapeHtml(v.page_id||'')}" placeholder="123456789"></label><label>${t('instagram_actor_id')}<input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="opcional"></label><label>${t('landing_url')}<input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details>${publishingGuide}</div>`;
 return `<div class="setup-guide private-connection"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Ad destination</span><h3>Let's find your pages automatically</h3><p>Using the token you already pasted, the dashboard tries to load your Facebook Pages, connected Instagram, and website. Usually you only choose the correct Page and continue.</p><div class="guide-actions"><button class="btn primary" type="button" data-action-code="discoverMetaAssets('${escapeHtml(v.ad_account_id||'')}')">Find Pages and Instagram</button><button class="btn" type="button" data-action-code="openChat('Help me choose the right Facebook Page for my ads.')">${t('ask_agent')}</button></div>${current?`<p class="notice">Saved now: ${current}</p>`:''}</div><aside class="guide-checklist"><b>What we are finding</b><ol><li>Your Facebook Page for publishing ads.</li><li>Your connected Instagram, if one exists.</li><li>Your website or landing page link.</li></ol></aside></section><div id="destination-discovery-results" class="setup-guide"></div><details class="fallback-details"><summary>Only if your Page does not appear</summary><form class="manual-account onboarding-mini two" data-submit-code="saveOnboardingSetupConfig(event)"><b>Paste details manually</b><p>Use this only if Meta does not return your pages. The agent can also help you find them by chat.</p><label>${t('page_id')}<input name="page_id" value="${escapeHtml(v.page_id||'')}" placeholder="123456789"></label><label>${t('instagram_actor_id')}<input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="optional"></label><label>${t('landing_url')}<input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></label><button class="btn primary" type="submit">${t('save_setup')}</button></form></details>${publishingGuide}</div>`;
}
function directPublishingState(){
 const v=state.config.setup_values||{};
 const publishing=state.config.publishing||{};
 const tokenSet=Boolean(v.meta_publishing_access_token_set||publishing.token_set);
 const ready=Boolean(publishing.ready||publishing.ok);
 const page=v.page_id||publishing.page_id||'';
 const savedAt=v.meta_publishing_token_saved_at?new Date(v.meta_publishing_token_saved_at).toLocaleString():'';
 const title=lang==='es'?'Publicación directa':'Direct publishing';
 const body=ready?(lang==='es'?'El agente puede publicar en la página y dejar contenido orgánico listo para aprobar.':'The agent can publish to the Page and prepare organic content for approval.'):(tokenSet?(lang==='es'?'Clave guardada. Revisa que tenga acceso a la página antes de publicar desde el agente.':'Key saved. Check that it can access the Page before publishing from the agent.'):(lang==='es'?'Opcional: conecta la app Live de publicaciones para publicar contenido orgánico desde Telegram. Los anuncios de WhatsApp usan primero la app principal de Ads.':'Optional: connect the Live publishing app for organic posting from Telegram. WhatsApp ads use the primary Ads app first.'));
 const badge=ready?(lang==='es'?'Lista':'Ready'):(tokenSet?(lang==='es'?'Revisar':'Check'):(lang==='es'?'Opcional':'Optional'));
 const placeholder=tokenSet?(lang==='es'?'Clave guardada. Pega otra solo para cambiarla.':'Key saved. Paste another only to replace it.'):'EAA...';
 return {v,publishing,tokenSet,ready,page,savedAt,title,body,badge,placeholder};
}
function directPublishingGuide(onboarding=false){
 const s=directPublishingState();
 const appsUrl='https://business.facebook.com/latest/settings/apps';
 const usersUrl='https://business.facebook.com/latest/settings/system-users';
 const shots=lang==='es'?[
  ['1','Crea una app básica separada','Usa una segunda app solo para publicaciones. Ponla en vivo con la URL de privacidad.','meta-business-01-open-apps-menu.png'],
  ['2','Asigna esa app al System User','Puede ser el mismo System User, pero debe tener acceso a la app Live y a la página.','meta-business-20-assign-app.png'],
  ['3','Genera una clave seleccionando esa app','En Generate token elige la app Live de publicaciones. Esa elección importa.','meta-business-24-select-app-token.png'],
  ['4','Marca permisos de página','Usa pages_manage_posts y pages_read_engagement para publicar contenido orgánico desde el agente.','meta-business-27-token-permissions-middle.png']
 ]:[
  ['1','Create a separate basic app','Use a second app only for publishing. Set it Live with the privacy URL.','meta-business-01-open-apps-menu.png'],
  ['2','Assign that app to the System User','It can be the same System User, but it must access the Live app and Page.','meta-business-20-assign-app.png'],
  ['3','Generate a key selecting that app','In Generate token choose the Live publishing app. That selection matters.','meta-business-24-select-app-token.png'],
  ['4','Select Page permissions','Use pages_manage_posts and pages_read_engagement for organic posting from the agent.','meta-business-27-token-permissions-middle.png']
 ];
 const shotCards=shots.map(([num,title,body,img])=>`<div class="guide-card direct-publishing-shot"><button class="direct-shot-button" type="button" data-action-code="openMetaScreenshot(${chatArg(img)},${chatArg(title)})"><img src="${metaAssetSrc(img)}" alt="${escapeHtml(title)}" loading="lazy"><span>${escapeHtml(num)}</span></button><b>${escapeHtml(title)}</b><p>${escapeHtml(body)}</p></div>`).join('');
 const keyNote=lang==='es'?'Importante: no basta con “asignar” dos apps al mismo System User. La clave debe generarse seleccionando la app Live de publicaciones. La primera clave de anuncios sigue sirviendo para campañas/cuentas; esta segunda clave se usa solo para crear posts nativos y publicaciones aprobables.':'Important: assigning two apps to the same System User is not enough. The key must be generated by selecting the Live publishing app. The first ads key still handles campaigns/accounts; this second key is only for native posts and approval-ready social publishing.';
 const installerNote=lang==='es'?'Si tienes instalación gratis, puedes dejar este paso al equipo. Si prefieres hacerlo tú, sigue estas capturas y pega la clave aquí.':'If you have free installation, you can leave this step to the team. If you prefer doing it yourself, follow these screenshots and paste the key here.';
 const headline=lang==='es'?'Opcional avanzado: publicar posts desde el agente':'Advanced optional: publish posts from the agent';
 const summary=lang==='es'?'Opcional: clave de Publicación directa para posts y creativos nativos':'Optional: Direct publishing key for native posts and creatives';
 const formClass=onboarding?'onboarding-mini two direct-publishing-form':'form-grid direct-publishing-form';
 const tokenField=onboarding
  ? `<label class="wide">${lang==='es'?'Clave de la app Live de publicaciones':'Live publishing app key'}<span class="field-help">${lang==='es'?'Para publicaciones orgánicas: pages_manage_posts y pages_read_engagement. Se guarda solo aquí.':'For organic publishing: pages_manage_posts and pages_read_engagement. Stored only here.'}</span><input type="password" name="token" value="" placeholder="${escapeHtml(s.placeholder)}" autocomplete="off"></label>`
  : `<div class="field wide"><label>${lang==='es'?'Clave de la app Live de publicaciones':'Live publishing app key'}</label><span class="field-help">${lang==='es'?'Para publicaciones orgánicas: pages_manage_posts y pages_read_engagement. Se guarda solo aquí.':'For organic publishing: pages_manage_posts and pages_read_engagement. Stored only here.'}</span><input type="password" name="token" value="" placeholder="${escapeHtml(s.placeholder)}" autocomplete="off"></div>`;
 const actions=`<div class="${onboarding?'wide onboarding-step-actions':'field wide'}"><div class="mode-actions"><button class="btn primary" type="submit">${s.tokenSet?(lang==='es'?'Cambiar clave':'Replace key'):(lang==='es'?'Guardar publicación directa':'Save direct publishing')}</button><button class="btn" type="button" data-action-code="testPublishingConnection()">${lang==='es'?'Revisar conexión':'Check connection'}</button>${s.tokenSet?`<button class="btn danger" type="button" data-action-code="disconnectPublishingConfig()">${lang==='es'?'Desconectar':'Disconnect'}</button>`:''}</div></div>`;
 const markup=`<div class="setup-guide direct-publishing-guide"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">${lang==='es'?'Publicación directa':'Direct publishing'}</span><h3>${headline}</h3><p>${escapeHtml(installerNote)}</p><div class="guide-actions"><a class="btn" href="${appsUrl}" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir Apps':'Open Apps'}</a><a class="btn" href="${usersUrl}" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir System Users':'Open System Users'}</a><a class="btn" href="https://admiraia.uboost.lat/privacy" target="_blank" rel="noopener noreferrer">${lang==='es'?'URL de privacidad':'Privacy URL'}</a></div></div><aside class="guide-checklist"><b>${lang==='es'?'Qué habilita':'What it enables'}</b><ol><li>${lang==='es'?'Posts diarios listos para aprobar.':'Daily posts ready for approval.'}</li><li>${lang==='es'?'Creativos de anuncio usando posts nativos.':'Ad creatives using native posts.'}</li><li>${lang==='es'?'Menos fricción cuando Meta rechaza creativos de una app en desarrollo.':'Less friction when Meta rejects creatives from a development app.'}</li></ol></aside></section><div class="direct-publishing-shots">${shotCards}</div><div class="guide-panel"><b>${lang==='es'?'Sobre la segunda clave':'About the second key'}</b><p>${escapeHtml(keyNote)}</p></div><form class="${formClass}" data-submit-code="savePublishingConfig(event)">${tokenField}${actions}</form></div>`;
 return onboarding?`<details class="fallback-details direct-publishing-onboarding"><summary>${summary}</summary>${markup}</details>`:markup;
}
function firstActionableOnboardingIndex(steps){
 const next=steps.findIndex(s=>s.status!=='ok');
 return next>=0?next:Math.max(0,steps.length-1);
}
function rememberOnboardingStep(stepId){
 if(!stepId)return;
 try{localStorage.setItem(ONBOARDING_STEP_KEY,stepId)}catch(_err){}
}
function clearRememberedOnboardingStep(){
 try{localStorage.removeItem(ONBOARDING_STEP_KEY)}catch(_err){}
}
function restoreOnboardingStepIndex(steps){
 let saved='';
 try{saved=localStorage.getItem(ONBOARDING_STEP_KEY)||''}catch(_err){}
 if(!saved)return false;
 const idx=steps.findIndex(s=>s.id===saved);
 if(idx<0||steps[idx].status==='ok')return false;
 onboardingFlowStep=idx;
 onboardingFlowTouched=true;
 return true;
}
function setOnboardingFlowStep(index){
 const steps=onboardingSteps();
 const max=Math.max(0,steps.length-1);
 onboardingFlowTouched=true;
 onboardingFlowStep=Math.max(0,Math.min(max,Number(index)||0));
 rememberOnboardingStep((steps[onboardingFlowStep]||{}).id);
 renderOnboardingFlow();
}
function advanceOnboardingAfterLoad(){
 const steps=onboardingSteps();
 const next=firstActionableOnboardingIndex(steps);
 if(next>onboardingFlowStep)onboardingFlowStep=next;
 rememberOnboardingStep((steps[onboardingFlowStep]||{}).id);
 renderOnboardingFlow();
}
function compactStepBadge(status){
 const ready=status==='ok';
 return `<span class="activation-status ${ready?'ready':'pending'}"><span>${ready?'✓':'·'}</span>${ready?(lang==='es'?'Listo':'Ready'):(lang==='es'?'Pendiente':'Pending')}</span>`;
}
function compactPasswordSetup(ready){
 if(ready)return `<div class="activation-complete-line">${lang==='es'?'Contraseña guardada en este equipo.':'Password saved on this device.'}</div>`;
 return `<form class="activation-form password-grid" data-submit-code="setDashboardPasswordFromOnboarding(event)">
  <label>${lang==='es'?'Contraseña':'Password'}<input id="new-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Mínimo 8 caracteres':'At least 8 characters'}"></label>
  <label>${lang==='es'?'Repetir contraseña':'Repeat password'}<input id="confirm-dashboard-password" type="password" autocomplete="new-password" minlength="8" placeholder="${lang==='es'?'Escríbela otra vez':'Type it again'}"></label>
  <label class="activation-check"><input id="new-dashboard-remember" type="checkbox" checked> ${lang==='es'?'Recordar este equipo':'Remember this device'}</label>
  <div class="unlock-error" id="dashboard-password-error"></div>
  <button class="btn primary" type="submit">${lang==='es'?'Guardar contraseña':'Save password'}</button>
 </form>`;
}
function compactMetaSetup(){
 const v=state.config.setup_values||{};
 const publishing=state.config.publishing||{};
 const adsTokenSet=Boolean(v.meta_access_token_set);
 const publishingTokenSet=Boolean(v.meta_publishing_access_token_set||publishing.token_set);
 const account=v.ad_account_id||'';
 const page=v.page_id||publishing.page_id||'';
 const adsPlaceholder=adsTokenSet?(lang==='es'?'Token de anuncios guardado':'Ads token saved'):(lang==='es'?'Pega el token de anuncios':'Paste the ads token');
 const pagePlaceholder=publishingTokenSet?(lang==='es'?'Token de página guardado':'Page token saved'):(lang==='es'?'Pega el token para publicar':'Paste the publishing token');
 return `<div class="activation-form">
  <div class="meta-token-pair">
   <label><span>${lang==='es'?'Token 1 · Anuncios':'Token 1 · Ads'}</span><input id="meta-token-input" type="password" autocomplete="off" placeholder="${adsPlaceholder}" data-input-code="scheduleMetaTokenAutoSave()" data-paste-code="setTimeout(scheduleMetaTokenAutoSave,0)"><small>${adsTokenSet?'✓ ':''}${lang==='es'?'Busca cuentas publicitarias automáticamente.':'Finds ad accounts automatically.'}</small></label>
   <label><span>${lang==='es'?'Token 2 · Publicación Live':'Token 2 · Live publishing'}</span><input id="meta-publishing-token-input" type="password" autocomplete="off" placeholder="${pagePlaceholder}" data-input-code="schedulePublishingTokenAutoSave()" data-paste-code="schedulePublishingTokenAutoSave(event)"><small>${publishingTokenSet?'✓ ':''}${lang==='es'?'Publica en la Página y, con permisos de anuncios, crea WhatsApp nativo.':'Publishes to the Page and, with ads permissions, creates native WhatsApp ads.'}</small></label>
  </div>
  <div class="activation-selection-strip">
   <span class="${account?'ready':''}">${account?'✓ ':''}${lang==='es'?'Cuenta':'Account'}${account?`: ${escapeHtml(account)}`:''}</span>
   <span class="${page?'ready':''}">${page?'✓ ':''}${lang==='es'?'Página':'Page'}${page?`: ${escapeHtml(page)}`:''}</span>
  </div>
  <div id="social-account-results" class="activation-results"></div>
  <div id="destination-discovery-results" class="activation-results"></div>
 </div>`;
}
function compactAgentSetup(){
 const model=state.config.agent_model||{};
 const studio=state.config.creative_studio||{};
 // NVIDIA NIM is the safe first-run brain; ChatGPT remains opt-in.
 const brain=model.brain_provider||'nvidia_nim';
 const apiProviders=['nvidia_nim','openai_api','minimax','custom_api'];
 const provider=brain==='openai_codex'?'openai_codex':(apiProviders.includes(brain)?brain:'nvidia_nim');
 const isChatGpt=provider==='openai_codex';
 const chatgptConnected=Boolean(model.chatgpt_connected);
 const connections=model.connections||{};
 const selected=connections[provider]||{};
 const defaults={
  openai_codex:{base:'',model:model.hermes_model||'gpt-5.6-luna'},
  nvidia_nim:{base:'https://integrate.api.nvidia.com/v1',model:'z-ai/glm-5.2'},
  openai_api:{base:'https://api.openai.com/v1',model:'gpt-4.1-mini'},
  minimax:{base:'https://api.minimax.io/v1',model:'MiniMax-M3'},
  custom_api:{base:'',model:''}
 };
 const base=selected.base_url||model.base_url||defaults[provider].base;
 const modelName=isChatGpt
  ? (chatgptConnected?(selected.model||(model.hermes_model_user_selected?model.hermes_model:'')||defaults[provider].model):'')
  : (selected.model||model.model||defaults[provider].model);
 const keySet=Boolean(selected.api_key_set||(provider===brain&&model.api_key_set));
 const imageConnected=Boolean(studio.codex_image_connected||model.codex_image_connected);
 const imageReady=Boolean(studio.codex_image_ready||model.codex_image_ready);
 const options=(model.nvidia_model_options||[]).map(value=>`<option value="${escapeHtml(value)}"></option>`).join('');
 const compactHermesModel=isChatGpt?(brain==='openai_codex'&&model.hermes_model_user_selected&&model.hermes_model?model.hermes_model:'gpt-5.6-luna'):'';
 return `<form id="agent-model-form" class="activation-form" data-submit-code="saveSetupConfig(event)">
  <input type="hidden" name="agent_chat_provider" value="${escapeHtml(provider)}">
  <input type="hidden" name="agent_chat_api" value="openai-chat-completions">
  <input type="hidden" name="agent_chat_base_url" value="${escapeHtml(base)}">
  <input type="hidden" name="hermes_model" value="${escapeHtml(compactHermesModel)}">
  <input type="hidden" name="codex_image_source" value="dedicated_chatgpt">
  <input type="hidden" name="codex_image_hermes_model" value="gpt-5.5">
  <div class="activation-model-grid">
   <label>${lang==='es'?'Proveedor':'Provider'}<select id="compact-agent-provider" data-change-code="selectCompactAgentProvider(event)">
   <option value="openai_codex" ${provider==='openai_codex'?'selected':''}>${lang==='es'?'ChatGPT suscripción':'ChatGPT subscription'}</option>
   <option value="nvidia_nim" ${provider==='nvidia_nim'?'selected':''}>NVIDIA NIM</option>
    <option value="openai_api" ${provider==='openai_api'?'selected':''}>OpenAI API</option>
    <option value="minimax" ${provider==='minimax'?'selected':''}>MiniMax</option>
   <option value="custom_api" ${provider==='custom_api'?'selected':''}>${lang==='es'?'Otra API':'Other API'}</option>
   </select></label>
   <label id="compact-agent-model-field" class="${isChatGpt&&!chatgptConnected?'hidden':''}">${lang==='es'?'Modelo':'Model'}<input name="agent_chat_model" value="${escapeHtml(modelName)}" list="${provider==='nvidia_nim'?'nvidia-model-options':''}" placeholder="${isChatGpt?(lang==='es'?'Conecta ChatGPT primero':'Connect ChatGPT first'):(lang==='es'?'Nombre del modelo':'Model name')}" ${isChatGpt&&!chatgptConnected?'disabled':''}><datalist id="nvidia-model-options">${options}</datalist></label>
   <label id="compact-agent-key-field" class="activation-key-field ${isChatGpt?'hidden':''}">${lang==='es'?'API key':'API key'}<input type="password" name="agent_chat_api_key" autocomplete="off" placeholder="${keySet?(lang==='es'?'API key guardada':'API key saved'):(lang==='es'?'Pega la API key':'Paste the API key')}"></label>
   <label id="compact-agent-base-field" class="${provider==='custom_api'?'':'hidden'}">${lang==='es'?'URL de la API':'API URL'}<input id="compact-agent-base-input" ${provider==='custom_api'?'name="agent_chat_base_url"':''} value="${escapeHtml(base)}" placeholder="https://..." data-input-code="syncCompactAgentBase(event)"></label>
   <button id="compact-agent-save-button" class="btn primary ${isChatGpt?'hidden':''}" type="submit" name="agent_model_action" value="set_primary">${keySet&&provider===brain?(lang==='es'?'Modelo listo':'Model ready'):(lang==='es'?'Guardar modelo':'Save model')}</button>
  </div>
  <div class="activation-model-hint"><span>${lang==='es'?`También puedes usar tu suscripción de ChatGPT como modelo principal.<small>Solo se puede conectar ChatGPT Plus o superior; una cuenta Free no sirve como modelo principal. Luna se elegirá automáticamente.</small>`:`You can also use your ChatGPT subscription as the primary model.<small>Only ChatGPT Plus or higher can be connected; a Free account cannot be the primary model. Luna is selected automatically.</small>`}</span><button class="btn" type="button" data-provider="openai_codex" data-action-code="selectCompactAgentProvider(event)">${lang==='es'?'ChatGPT suscripción':'ChatGPT subscription'}</button></div>
  <div id="compact-agent-chatgpt-row" class="activation-chatgpt-row ${isChatGpt?'':'hidden'}"><div><b>${lang==='es'?'Conectar tu suscripción de ChatGPT':'Connect your ChatGPT subscription'}</b><small>${lang==='es'?'Usa tu cuenta de ChatGPT/Codex como cerebro principal del agente. Requiere Plus o superior; Luna se selecciona automáticamente.':'Use your ChatGPT/Codex account as the agent’s primary brain. Plus or higher is required; Luna is selected automatically.'}</small></div><button class="btn primary" type="button" data-action-code="connectChatGpt(event)">${model.chatgpt_connected?(lang==='es'?'ChatGPT conectado':'ChatGPT connected'):(lang==='es'?'Conectar ChatGPT':'Connect ChatGPT')}</button></div>
  <div id="chatgpt-connect-result" class="chatgpt-connect-result hidden"></div>
  <div class="activation-image-row ${imageReady?'ready':''}">
   <div><span class="activation-mini-icon">${imageReady?'✓':'IMG'}</span><div><b>${lang==='es'?'ChatGPT para imágenes · opcional':'ChatGPT for images · optional'}</b><small>${imageReady?(lang==='es'?'Cuenta conectada':'Account connected'):(lang==='es'?'Puedes conectarlo después; no bloquea el modelo ni Telegram.':'You can connect it later; it does not block the model or Telegram.')}</small></div></div>
   ${imageConnected?`<button class="btn" type="button" data-action-code="disconnectAgentModel('image')">${lang==='es'?'Cambiar cuenta':'Change account'}</button>`:`<button class="btn" type="button" data-action-code="connectImageChatGpt(event)">${lang==='es'?'Conectar ChatGPT':'Connect ChatGPT'}</button>`}
  </div>
  <div id="image-chatgpt-connect-result" class="chatgpt-connect-result hidden"></div>
 </form>`;
}
function selectCompactAgentProvider(event){
 const form=event?.target?.closest?.('form');if(!form)return;
 const picked=event?.target?.closest?.('[data-provider]')?.dataset?.provider;
 const provider=String(picked||event.target.value||'nvidia_nim');
 const defaults={
  openai_codex:{base:'',model:'gpt-5.6-luna'},
  nvidia_nim:{base:'https://integrate.api.nvidia.com/v1',model:'z-ai/glm-5.2'},
  openai_api:{base:'https://api.openai.com/v1',model:'gpt-4.1-mini'},
  minimax:{base:'https://api.minimax.io/v1',model:'MiniMax-M3'},
  custom_api:{base:'',model:''}
 };
 const preset=defaults[provider]||defaults.nvidia_nim;
 form.elements.agent_chat_provider.value=provider;
 form.elements.agent_chat_base_url.value=preset.base;
 form.elements.agent_chat_model.value=provider==='openai_codex'?'':preset.model;
 if(form.elements.hermes_model)form.elements.hermes_model.value=provider==='openai_codex'?'gpt-5.6-luna':'';
 form.elements.agent_chat_api_key.value='';
 const baseField=qs('#compact-agent-base-field');const baseInput=qs('#compact-agent-base-input');
 const keyField=qs('#compact-agent-key-field');const saveButton=qs('#compact-agent-save-button');const chatGptRow=qs('#compact-agent-chatgpt-row');const modelField=qs('#compact-agent-model-field');const modelInput=form.elements.agent_chat_model;
 const isChatGpt=provider==='openai_codex';
 if(keyField)keyField.classList.toggle('hidden',isChatGpt);
 if(saveButton)saveButton.classList.toggle('hidden',isChatGpt);
 if(chatGptRow)chatGptRow.classList.toggle('hidden',!isChatGpt);
 if(modelField)modelField.classList.toggle('hidden',isChatGpt);
 if(modelInput){modelInput.disabled=isChatGpt;modelInput.placeholder=isChatGpt?(lang==='es'?'Conecta ChatGPT primero':'Connect ChatGPT first'):(lang==='es'?'Nombre del modelo':'Model name')}
 if(baseField)baseField.classList.toggle('hidden',provider!=='custom_api');
 if(baseInput){baseInput.value=preset.base;if(provider==='custom_api')baseInput.setAttribute('name','agent_chat_base_url');else baseInput.removeAttribute('name')}
}
function syncCompactAgentBase(event){
 const form=event?.target?.closest?.('form');const hidden=form?.querySelector?.('input[type="hidden"][name="agent_chat_base_url"]');if(hidden)hidden.value=String(event.target.value||'');
}
function compactTelegramStatusMarkup(value={}){
 const v=value||{};
 const ready=Boolean(v.enabled&&v.bot_configured&&v.chat_id);
 const detectButton=!ready&&v.bot_configured?`<button class="btn primary telegram-detect-button" type="button" data-action-code="detectTelegramChats()">${lang==='es'?'Ya envié hola · Detectar mi chat':'I sent hello · Detect my chat'}</button>`:'';
 return `<div class="activation-wait ${ready?'ready':''}"><span>${ready?'✓':'•••'}</span><div><b>${ready?(lang==='es'?'Telegram conectado':'Telegram connected'):(v.bot_configured?(lang==='es'?'Ahora envía “hola” a tu bot':'Now send “hello” to your bot'):(lang==='es'?'Pega el token para empezar':'Paste the token to start'))}</b><small>${ready?(lang==='es'?'Tu agente ya puede responderte.':'Your agent can now reply.'):(v.bot_configured?(lang==='es'?'Abre Telegram, entra al bot que creaste y envíale “hola”. Después toca Detectar mi chat; también lo buscaré automáticamente.':'Open Telegram, enter the bot you created, and send “hello”. Then click Detect my chat; I will also look for it automatically.'):'')}</small></div>${detectButton}</div>`;
}
function compactTelegramSetup(){
 const v=state.config.telegram_agent||{};
 return `<form class="activation-form telegram-token-form">
  <div class="activation-telegram-row">
   <label class="telegram-token-zone ${v.bot_configured?'saved':''}">${lang==='es'?'Token del bot':'Bot token'}<span class="field-help" data-telegram-token-help>${v.bot_configured?(lang==='es'?'Token guardado. Ahora envía “hola”.':'Token saved. Now send “hello”.'):(lang==='es'?'Pega el token de BotFather.':'Paste the BotFather token.')}</span><input type="password" name="bot_token" autocomplete="off" placeholder="${v.bot_configured?(lang==='es'?'Token guardado':'Token saved'):'123456:ABC...'}" data-input-code="autoSaveTelegramToken(event)" data-paste-code="autoSaveTelegramToken(event)"></label>
   <input type="hidden" name="language" value="${escapeHtml(v.language||lang||'es')}">
   <a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">BotFather</a>
  </div>
 </form>
 <div id="telegram-results" class="activation-results">${compactTelegramStatusMarkup(v)}</div>`;
}
function compactActivationSection(number,title,status,body){
 return `<section class="activation-section ${status==='ok'?'complete':''}" id="activation-${number}"><div class="activation-section-head"><span class="activation-number">${number}</span><h2>${title}</h2>${compactStepBadge(status)}</div><div class="activation-section-body">${body}</div></section>`;
}
let compactAccountAutoDiscoveryKey='';
function maybeAutoDiscoverCompactSetup(){
 const v=state.config.setup_values||{};
 if(v.meta_access_token_set&&!v.ad_account_id&&compactAccountAutoDiscoveryKey!=='accounts'){
  compactAccountAutoDiscoveryKey='accounts';
  setTimeout(()=>refreshSocialAccounts().catch(()=>{}),100);
 }else if(v.ad_account_id&&!v.page_id){
  const key=`page:${v.ad_account_id}`;
  if(compactAccountAutoDiscoveryKey!==key){
   compactAccountAutoDiscoveryKey=key;
   setTimeout(()=>discoverMetaAssets(v.ad_account_id).catch(()=>{}),100);
  }
 }
}
function renderOnboardingFlow(){
 const flow=qs('#onboarding-flow');if(!flow)return;
 if(uiWorkbenchPreview){flow.classList.remove('open');flow.innerHTML='';return}
 const doneState=state.onboarding||{};
 const needsFirstPassword=Boolean(state.config.dashboard_password_required&&!state.config.dashboard_password_set);
 if(doneState.completed&&!doneState.requires_repair&&!needsFirstPassword){clearRememberedOnboardingStep();stopTelegramHelloPolling();flow.classList.remove('open');flow.innerHTML='';return}
 const steps=onboardingSteps();
 const doneCount=steps.filter(item=>item.status==='ok').length;
 const licenseReady=Boolean(state.setup?.summary?.license_ready);
 flow.classList.add('open');
 flow.innerHTML=`<div class="activation-shell">
  <header class="activation-header"><div><span class="activation-kicker">Admira IA</span><h1>${lang==='es'?'Activa tu agente':'Activate your agent'}</h1><p>${lang==='es'?'Completa esta página de arriba hacia abajo.':'Complete this page from top to bottom.'}</p></div><div class="activation-progress"><strong>${doneCount}/${steps.length}</strong><span>${lang==='es'?'completados':'complete'}</span><div><i data-progress="${doneCount}"></i></div></div></header>
  ${!licenseReady?`<div class="activation-install-alert"><b>${lang==='es'?'La activación de la instalación necesita revisión.':'Installation activation needs attention.'}</b><span>${lang==='es'?'La licencia se corrige desde el instalador o con soporte; nunca se pega aquí.':'The license is repaired through the installer or support; it is never pasted here.'}</span></div>`:''}
  <main class="activation-rail">
   ${compactActivationSection(1,lang==='es'?'Crea tu contraseña':'Create your password',steps[0].status,compactPasswordSetup(steps[0].status==='ok'))}
   ${compactActivationSection(2,lang==='es'?'Conecta Meta':'Connect Meta',steps[1].status,compactMetaSetup())}
   ${compactActivationSection(3,lang==='es'?'Elige el modelo':'Choose the model',steps[2].status,compactAgentSetup())}
   ${compactActivationSection(4,lang==='es'?'Conecta Telegram':'Connect Telegram',steps[3].status,compactTelegramSetup())}
  </main>
  <footer class="activation-footer"><span>${lang==='es'?'Tus claves permanecen en esta instalación.':'Your keys stay in this installation.'}</span><button class="btn primary" type="button" data-action-code="completeOnboarding()">${lang==='es'?'Revisar y abrir dashboard':'Review and open dashboard'}</button></footer>
 </div>`;
 const width=`${Math.round((doneCount/Math.max(steps.length,1))*100)}%`;
 const progressBar=flow.querySelector('.activation-progress i');if(progressBar)progressBar.style.width=width;
 maybeAutoDiscoverCompactSetup();
 startTelegramHelloPolling();
}
function maybeAutoDiscoverDestination(stepId){
 if(stepId!=='destination')return;
 const v=state.config.setup_values||{};const account=v.ad_account_id||'';
 if(!account||v.page_id)return;
 const key=`${account}:${v.page_id||''}:${v.landing_url||''}`;
 if(destinationAutoDiscoveryKey===key)return;
 destinationAutoDiscoveryKey=key;
 setTimeout(()=>discoverMetaAssets(account),60);
}
function usageCheatSheetMarkup(onboarding=false){const cards=lang==='es'?[
 ['Habla primero','Usa el chat como si hablaras con un manager: "qué hacemos hoy", "revisa presupuesto", "prepara una campaña para mi oferta".'],
 ['El dashboard es control','Mira números, aprobaciones y actividad cuando quieras verificar qué vio el agente y qué dejó preparado.'],
 ['Pide una cosa concreta','Mientras más simple la petición, mejor responde: producto, país, presupuesto y objetivo. Si falta algo, el agente debe preguntarte.'],
 ['Crear en pausa es borrador seguro','Cuando algo nuevo nace en pausa, todavía no empezó a gastar ni aprender. Es distinto a prender, pausar y reactivar campañas vivas muchas veces.'],
 ['Primero preparar en pausa','Deja que lea datos reales, recomiende y prepare campañas sin gastar. Activa solo cuando quieras dar luz verde.'],
 ['Aprueba con calma','El chat puede preparar acciones, pero las decisiones riesgosas se confirman desde aprobaciones. Esa pausa es parte de la seguridad.'],
 ['Vuelve a esta guía','Si te pierdes, abre Configuración > Guía y pídele al agente un resumen en palabras simples.']
]:[
 ['Talk first','Use chat like a manager: "what should we do today", "review budget", "prepare a campaign for my offer".'],
 ['Dashboard is control','Use the dashboard to verify numbers, approvals, and activity when you want to see what the agent saw and prepared.'],
 ['Ask one concrete thing','Simple requests work best: product, country, budget, and goal. If something is missing, the agent should ask.'],
 ['Paused creation is a safe draft','When something new starts paused, it has not spent or learned yet. That is different from repeatedly pausing and resuming live campaigns.'],
 ['Prepare paused first','Let it read real data, recommend, and prepare campaigns without spending. Activate only when you want to give the green light.'],
 ['Approve calmly','Chat can prepare actions, but risky decisions are confirmed in approvals. That pause is part of the safety.'],
 ['Return to this guide','If you feel lost, open Setup > Guide and ask the agent for a plain-language catch-up.']
];return `<div class="${onboarding?'setup-guide':'guide-panel'}" id="${onboarding?'':'usage-guide-card'}"><div class="next-step"><div><b>${lang==='es'?'Guía rápida de uso':'Quick usage guide'}</b><p>${lang==='es'?'La filosofía: conversa con el agente y usa el dashboard para confirmar, aprobar y revisar.':'The philosophy: talk with the agent and use the dashboard to confirm, approve, and review.'}</p></div><button class="btn ask-btn" data-action-code="openChat(lang==='es'?'Explícame cómo usar este producto con palabras muy simples.':'Explain how to use this product in very simple words.')">${t('ask_agent')}</button></div><div class="trust-grid">${cards.map(c=>`<div class="trust-card"><b>${c[0]}</b><p>${c[1]}</p></div>`).join('')}</div></div>`}
function renderUsageCheatsheet(){const box=qs('#usage-cheatsheet');if(box)box.innerHTML=''}
function closeUsageGuide(){const box=qs('#guide-overlay');if(!box)return;box.classList.remove('open','product-tour','theme-choice');box.innerHTML=''}
function openUsageGuide(){
 const box=qs('#guide-overlay');if(!box)return;
 box.classList.remove('product-tour','theme-choice');
 box.innerHTML=`<div class="guide-modal-card"><div class="next-step"><div><h2>${lang==='es'?'Guía rápida':'Quick guide'}</h2><p>${lang==='es'?'Tarjetas cortas para recordar cómo usar el producto sin llenar la pantalla principal.':'Short cards to remember how to use the product without filling the main screen.'}</p></div><button class="btn" type="button" data-action-code="closeUsageGuide()">${lang==='es'?'Cerrar':'Close'}</button></div>${usageCheatSheetMarkup(false)}</div>`;
 box.classList.add('open')
}
let dashboardIntroTourIndex=0;
let dashboardIntroTourRetry=0;
function dashboardIntroTourSteps(){
 return lang==='es'?[
  {selectors:['#theme-toggle'],title:'Elige el estilo que más te guste',body:'Arriba, junto al menú, prueba Aurora, Sapphire y Ember ahora mismo. Elige el que más cómodo se sienta para trabajar; después seguimos con el resto del tour.'},
  {selectors:['#daily-brief-schedule-button'],title:'Elige la hora de tu lectura diaria',body:'Toca este botón para cambiar la hora del resumen de la mañana. La zona horaria se detecta automáticamente desde tu navegador.'},
  {selectors:['.agent-chat-bar'],title:'Habla con tu manager',body:'Esta barra es la forma principal de usar el producto. Escribe como si hablaras con una persona: “qué hago hoy”, “crea una campaña”, “revisa mis creativos”.'},
  {selectors:['.view-switcher'],title:'Cambia la forma de ver tus anuncios',body:'Control muestra lo importante del día. Timeline muestra anuncios activos. Vista total enseña métricas generales. Showcase es una vista más visual.'},
  {selectors:['#toggle-left-panel','.brief-zone .zone-label'],title:'Lectura diaria',body:'Aquí vive el resumen de la mañana. Si está cerrado, toca el encabezado para abrirlo y ver qué está vigilando el agente.'},
  {selectors:['#toggle-right-panel','.rail .zone-label'],title:'Aprobaciones y actividad',body:'Los cambios delicados aparecen aquí antes de ejecutarse. Es tu zona de seguridad para aprobar, rechazar y revisar qué se hizo.'},
  {selectors:['nav.tabs','.tabs'],title:'Menú principal',body:'Desde aquí entras a configuración, creador, audiencias, creativos y reportes. No necesitas usar todo: el chat también puede llevarte.'},
  {selectors:['.header-guide-btn'],title:'Guía rápida siempre disponible',body:'Si te pierdes, toca este botón. Abre tarjetas simples para recordar cómo usar el producto sin ruido.'}
 ]:[
  {selectors:['#theme-toggle'],title:'Choose your favorite style',body:'At the top, beside the menu, try Aurora, Sapphire, and Ember now. Pick the one that feels best to work in; then we continue the tour.'},
  {selectors:['#daily-brief-schedule-button'],title:'Choose your daily brief time',body:'Tap here to change the morning summary time. Your timezone is detected automatically from the browser.'},
  {selectors:['.agent-chat-bar'],title:'Talk to your manager',body:'This bar is the main way to use the product. Write naturally: “what should I do today”, “create a campaign”, “review my creatives”.'},
  {selectors:['.view-switcher'],title:'Switch ad views',body:'Control shows today’s essentials. Timeline shows active ads. Overview shows broader metrics. Showcase is more visual.'},
  {selectors:['#toggle-left-panel','.brief-zone .zone-label'],title:'Daily reading',body:'This is the morning summary. If it is closed, tap the header to open what the agent is watching.'},
  {selectors:['#toggle-right-panel','.rail .zone-label'],title:'Approvals and activity',body:'Sensitive actions appear here before execution. This is your safety area to approve, reject, and review what happened.'},
  {selectors:['nav.tabs','.tabs'],title:'Main menu',body:'Go to setup, creator, audiences, creatives, and reports from here. You do not need to use everything: chat can guide you too.'},
  {selectors:['.header-guide-btn'],title:'Quick guide anytime',body:'If you feel lost, tap this button. It opens simple reminder cards without cluttering the dashboard.'}
 ];
}
function dashboardIntroBlocked(){
 const unlock=qs('#unlock-overlay')?.classList.contains('open');
 const onboarding=qs('#onboarding-flow')?.classList.contains('open');
 const confirm=qs('#confirm-overlay')?.classList.contains('open');
 return uiWorkbenchPreview||unlock||onboarding||confirm||!(state?.onboarding?.completed);
}
function startDashboardIntroTourIfPending(){
 if(localStorage.getItem('dashboardIntroTourPending')!=='1')return;
 if(dashboardIntroBlocked()){
  dashboardIntroTourRetry+=1;
  if(dashboardIntroTourRetry<8)setTimeout(startDashboardIntroTourIfPending,700);
  return;
 }
 dashboardIntroTourRetry=0;
 localStorage.removeItem('dashboardIntroTourPending');
 startDashboardIntroTour(true);
}
function startDashboardIntroTour(force=false){
 if(!force&&localStorage.getItem('dashboardIntroTourDone')==='1')return;
 const box=qs('#guide-overlay');if(!box)return;
 dashboardIntroTourIndex=0;
 box.classList.add('open','product-tour');
 renderDashboardIntroTour();
}
function finishDashboardIntroTour(){
 const box=qs('#guide-overlay');if(box){box.classList.remove('open','product-tour','theme-choice');box.innerHTML=''}
 localStorage.setItem('dashboardIntroTourDone','1');
}
function nextDashboardIntroTour(){dashboardIntroTourIndex+=1;renderDashboardIntroTour()}
function previousDashboardIntroTour(){dashboardIntroTourIndex=Math.max(0,dashboardIntroTourIndex-1);renderDashboardIntroTour()}
function findTourTarget(step){
 for(const selector of step.selectors||[]){const target=qs(selector);if(target&&target.getBoundingClientRect().width>0&&target.getBoundingClientRect().height>0)return target}
 return null;
}
function clampTourPosition(value,min,max){return Math.max(min,Math.min(value,max))}
function renderDashboardIntroTour(){
 const steps=dashboardIntroTourSteps();
 if(dashboardIntroTourIndex>=steps.length){finishDashboardIntroTour();return}
 const step=steps[dashboardIntroTourIndex];
 const target=findTourTarget(step);
 if(!target){dashboardIntroTourIndex+=1;renderDashboardIntroTour();return}
 target.scrollIntoView({block:'center',inline:'center',behavior:'smooth'});
 setTimeout(()=>renderDashboardIntroTourAtTarget(target,step,steps.length),170);
}
function renderDashboardIntroTourAtTarget(target,step,total){
 const box=qs('#guide-overlay');if(!box||!box.classList.contains('product-tour'))return;
 box.classList.toggle('theme-choice',dashboardIntroTourIndex===0);
 const rect=target.getBoundingClientRect();
 const pad=7;
 const spot={left:Math.max(8,rect.left-pad),top:Math.max(8,rect.top-pad),width:Math.min(window.innerWidth-16,rect.width+(pad*2)),height:Math.min(window.innerHeight-16,rect.height+(pad*2))};
 const cardWidth=Math.min(360,window.innerWidth-28);
 const cardHeight=210;
 const below=spot.top+spot.height+14;
 const above=spot.top-cardHeight-14;
 const top=below+cardHeight<window.innerHeight-12?below:Math.max(12,above);
 const left=clampTourPosition(spot.left+spot.width/2-cardWidth/2,14,window.innerWidth-cardWidth-14);
 const isLast=dashboardIntroTourIndex>=total-1;
 const count=lang==='es'?`Paso ${dashboardIntroTourIndex+1}/${total}`:`Step ${dashboardIntroTourIndex+1}/${total}`;
 const back=lang==='es'?'Atrás':'Back';
 const next=isLast?(lang==='es'?'Terminar':'Finish'):(lang==='es'?'Siguiente':'Next');
 const skip=lang==='es'?'Omitir':'Skip';
 box.innerHTML=`<div class="tour-spot" data-style-code="left:${spot.left}px;top:${spot.top}px;width:${spot.width}px;height:${spot.height}px"></div><article class="tour-card" data-style-code="left:${left}px;top:${top}px"><span class="tour-step-count">${count}</span><h2>${escapeHtml(step.title)}</h2><p>${escapeHtml(step.body)}</p><div class="tour-actions"><button class="btn tour-skip" type="button" data-action-code="finishDashboardIntroTour()">${skip}</button><button class="btn" type="button" ${dashboardIntroTourIndex===0?'disabled':''} data-action-code="previousDashboardIntroTour()">${back}</button><button class="btn primary" type="button" data-action-code="${isLast?'finishDashboardIntroTour()':'nextDashboardIntroTour()'}">${next}</button></div></article>`;
}
function scrollToUsageGuide(){openUsageGuide()}
function renderModeControl(){qs('#mode-control').innerHTML=`<div class="mode-panel"><div><h3>${lang==='es'?'Regla de seguridad':'Safety rule'}</h3><p>${lang==='es'?'Admira puede crear y corregir campañas completamente en pausa. Para activar, gastar, publicar o borrar, te pide una aprobación clara.':'Admira can create and fix fully paused campaigns. To activate, spend, publish, or delete, it asks for clear approval.'}</p></div><div class="mode-actions"><span class="badge ok">${lang==='es'?'Crear en pausa: permitido':'Paused setup: allowed'}</span><span class="badge warn">${lang==='es'?'Activar/gastar: aprobación':'Activate/spend: approval'}</span></div></div>`}
function renderGuardrails(){
 const g=state.config.guardrails||{};
 const r=state.config.profitability_rules||state.decision_memory?.profitability_rules||{};
 const opt=state.optimization?.state||{};const unlock=state.optimization?.unlock||{};const shop=state.optimization?.shopify||{};const optModeLabel=opt.mode==='shadow'?(lang==='es'?'observación':'shadow'):(lang==='es'?'desbloqueado':'unlocked');
 qs('#guardrails-panel').innerHTML=`<div class="settings-stack">
 <div class="onboarding-mini approval-rules-panel"><h3>${lang==='es'?'Reglas de aprobación':'Approval rules'}</h3><p class="notice">${lang==='es'?'No hay modos que elegir. Admira trabaja con una regla simple: prepara y crea en pausa; pide tu luz verde para activar, gastar, publicar, borrar o enviar datos sensibles.':'There are no modes to choose. Admira uses one simple rule: prepare and create paused; ask for your green light to activate, spend, publish, delete, or send sensitive data.'}</p><div class="trust-grid"><div class="trust-card"><b>${lang==='es'?'Puede hacer':'Allowed'}</b><p>${lang==='es'?'Analizar, proponer, generar creativos y crear estructuras pausadas sin gastar.':'Analyze, recommend, generate creatives, and create paused no-spend structures.'}</p></div><div class="trust-card"><b>${lang==='es'?'Pide aprobación':'Needs approval'}</b><p>${lang==='es'?'Activar campañas, gastar presupuesto, publicar visible, borrar o enviar datos sensibles.':'Activate campaigns, spend budget, publish visibly, delete, or send sensitive data.'}</p></div></div></div>
 <form class="onboarding-mini two profitability-rules" data-submit-code="saveProfitabilityRules(event)"><div class="wide"><h3>${lang==='es'?'Objetivos de rentabilidad por resultado':'Profitability targets by outcome'}</h3><p class="notice">${lang==='es'?'Ventas usan CPA y ROAS; leads usan CPL; mensajes usan costo por conversación.':'Sales use CPA and ROAS; leads use CPL; messages use cost per conversation.'}</p></div><label>${lang==='es'?'CPA objetivo (ventas)':'Target CPA (sales)'}<input name="target_cpa" type="number" min="0" step="1" value="${r.target_cpa||50}"></label><label>${lang==='es'?'CPL objetivo (leads)':'Target CPL (leads)'}<input name="target_cpl" type="number" min="0" step="1" value="${r.target_cpl||r.target_cpa||50}"></label><label>${lang==='es'?'Costo por conversación':'Cost per conversation'}<input name="target_cost_per_conversation" type="number" min="0" step="1" value="${r.target_cost_per_conversation||r.target_cpa||50}"></label><label>${lang==='es'?'ROAS mínimo sano':'Healthy ROAS floor'}<input name="target_roas" type="number" min="0" step=".1" value="${r.target_roas||2.5}"></label><label>${lang==='es'?'Margen de contribución %':'Contribution margin %'}<input name="contribution_margin_pct" type="number" min="0" max="100" step="1" value="${r.contribution_margin_pct||0}"></label><label>${lang==='es'?'Gasto mínimo antes de juzgar':'Min spend before judging'}<input name="min_spend_before_judging" type="number" min="0" step="1" value="${r.min_spend_before_judging||50}"></label><label>${lang==='es'?'Resultados mínimos antes de escalar':'Min results before scaling'}<input name="min_conversions_before_scaling" type="number" min="1" step="1" value="${r.min_conversions_before_scaling||3}"></label><label>${lang==='es'?'Frecuencia máxima antes de refrescar':'Max frequency before refresh'}<input name="max_frequency_before_refresh" type="number" min="0" step=".1" value="${r.max_frequency_before_refresh||3}"></label><label class="wide">${lang==='es'?'Notas para el agente':'Notes for the agent'}<textarea name="notes" rows="3">${escapeHtml(r.notes||'')}</textarea></label><button class="btn primary" type="submit">${lang==='es'?'Guardar rentabilidad':'Save profitability rules'}</button></form>
 <form class="onboarding-mini two" data-submit-code="saveOptimizationSettings(event)"><div class="wide"><h3>${lang==='es'?'Motor de optimización':'Optimization engine'} · ${escapeHtml(optModeLabel)}</h3><p class="notice">${lang==='es'?`Observación ${unlock.elapsed_days||0}/${unlock.minimum_days||14} días · decisiones maduras ${unlock.matured_outcomes||0}/${unlock.minimum_matured_outcomes||10}.`:`Shadow ${unlock.elapsed_days||0}/${unlock.minimum_days||14} days · matured outcomes ${unlock.matured_outcomes||0}/${unlock.minimum_matured_outcomes||10}.`}</p></div><label>${lang==='es'?'Reserva para tests %':'Test budget reserve %'}<input name="test_budget_percent" type="number" min="5" max="40" step="1" value="${opt.test_budget_percent||20}"></label><label>${lang==='es'?'Tope diario de cuenta (0 = sin tope)':'Account daily cap (0 = unset)'}<input name="account_daily_budget_cap" type="number" min="0" step="1" value="${opt.account_daily_budget_cap||0}"></label><label>${lang==='es'?'Espera después de cambios (horas)':'Cooldown after edits (hours)'}<input name="cooldown_hours" type="number" min="12" max="168" step="1" value="${opt.cooldown_hours||48}"></label><label>${lang==='es'?'Retraso de conversiones (horas)':'Conversion lag (hours)'}<input name="conversion_lag_hours" type="number" min="1" max="168" step="1" value="${opt.conversion_lag_hours||24}"></label><label>${lang==='es'?'Paso de escalado %':'Scaling step %'}<input name="scale_step_pct" type="number" min="1" max="20" step="1" value="${opt.scale_step_pct||10}"></label><button class="btn primary" type="submit">${lang==='es'?'Guardar optimización':'Save optimization'}</button><button class="btn" type="button" ${unlock.eligible?'':'disabled'} data-action-code="unlockOptimization()">${lang==='es'?'Confirmar y desbloquear':'Confirm and unlock'}</button></form>
 <form class="onboarding-mini two" data-submit-code="saveShopifyConfig(event)"><div class="wide"><h3>Shopify · ${shop.configured?(lang==='es'?'conectado':'connected'):(lang==='es'?'opcional':'optional')}</h3><p class="notice">${lang==='es'?'Se guardan solo totales diarios, devoluciones y claves hash. Nunca nombres, emails, direcciones ni IDs de pedido.':'Only daily totals, refunds, and hashed keys are stored. Never names, emails, addresses, or raw order IDs.'}</p></div><label>${lang==='es'?'Dominio myshopify.com':'myshopify.com domain'}<input name="shop_domain" value="${escapeHtml(shop.shop_domain||'')}" placeholder="tienda.myshopify.com"></label><label>${lang==='es'?'Token Admin de solo lectura':'Read-only Admin token'}<input name="admin_token" type="password" autocomplete="off" placeholder="${shop.token_set?(lang==='es'?'Token guardado; deja vacío para conservarlo':'Token saved; leave blank to keep it'):'shpat_...'}"></label><button class="btn primary" type="submit">${lang==='es'?'Guardar Shopify':'Save Shopify'}</button><button class="btn" type="button" data-action-code="testShopifyConnection()" ${shop.configured?'':'disabled'}>${lang==='es'?'Probar':'Test'}</button><button class="btn" type="button" data-action-code="syncShopifyOutcomes()" ${shop.configured?'':'disabled'}>${lang==='es'?'Sincronizar ventas':'Sync outcomes'}</button><p class="notice wide">${lang==='es'?`Última sincronización: ${escapeHtml(shop.last_success_at||'todavía no')}`:`Last sync: ${escapeHtml(shop.last_success_at||'not yet')}`}</p></form>
 </div>`;
}
function licenseLabel(status){
 if(status.valid&&status.license_term==='lifetime')return lang==='es'?'Activa de por vida':'Lifetime active';
 if(status.status==='cloud_server_missing'||status.status==='missing_unlock')return lang==='es'?'No se pudo validar con el servidor':'Could not validate with server';
 if(status.valid)return t('license_active');
 if(status.status==='missing')return t('license_missing');
 return t('license_invalid');
}
function licenseDetail(status){
 const detail=localText(status.detail||'');
 const mode=status.cloud_required?t('license_cloud'):t('license_local');
 const plan=status.plan==='agency'?(lang==='es'?'Extendida':'Extended'):(lang==='es'?'Individual':'Individual');
 const lifetime=status.license_term==='lifetime'?(lang==='es'?'De por vida':'Lifetime'):'';
 return [plan,lifetime,mode,detail].filter(Boolean).join(' · ');
}
function renderLicensePanel(){
 const status=state.config.license_status||{};const valid=Boolean(status.valid);
 const ent=state.license_entitlements||state.config.license_entitlements||{};
 const workspace=state.active_workspace||{};
 const binding=state.business_binding||{};
 const managed=state.managed_ad_accounts||binding.managed_ad_accounts||state.config.setup_values?.managed_ad_accounts||{};
 const bm=managed.business_manager||binding.business_manager||{};
 const accountUse=`${managed.used||0}/${managed.max_accounts||5}`;
 const planName=ent.is_agency?(lang==='es'?'Extendida':'Extended'):(lang==='es'?'Individual':'Individual');
 const activeName=workspace.name||[binding.ad_account_id,binding.page_id].filter(Boolean).join(' · ')||(lang==='es'?'Aún sin negocio activo':'No active business yet');
 const individualCopy=lang==='es'?'Tu instalación estándar puede cuidar hasta 5 cuentas publicitarias, siempre dentro del mismo Business Manager. Si cambias de Business Manager, empezamos limpio para no mezclar negocios.':'Your standard install can manage up to 5 ad accounts, all under the same Business Manager. If you change Business Manager, we start clean to avoid mixing businesses.';
 const extendedCopy=lang==='es'?'Puedes trabajar varias cuentas publicitarias bajo un mismo Business Manager. Esta instalación mantiene un negocio activo y hasta 5 cuentas conectadas.':'You can work with several ad accounts under one Business Manager. This install keeps one active business and up to 5 connected accounts.';
 qs('#license-panel').innerHTML=`<div class="mode-panel license-status-card"><div><h3>${t('license_panel_title')}: ${licenseLabel(status)}</h3><p>${ent.is_agency?extendedCopy:individualCopy}</p><p class="notice">${licenseDetail(status)}</p></div><div class="mode-actions"><button class="btn ${valid?'':'primary'}" data-action-code="activateLicense()">${t('license_activate')}</button></div></div><div class="trust-grid license-limits-grid"><div class="trust-card"><b>${lang==='es'?'Plan':'Plan'}</b><p>${planName}</p></div><div class="trust-card"><b>${lang==='es'?'Equipos permitidos':'Allowed devices'}</b><p>${ent.max_devices||1}</p></div><div class="trust-card"><b>${lang==='es'?'Negocio activo':'Active business'}</b><p>${escapeHtml(activeName)}</p></div><div class="trust-card"><b>${lang==='es'?'Cuentas Meta':'Meta accounts'}</b><p>${escapeHtml(accountUse)} ${lang==='es'?'en el mismo BM':'same BM'}</p></div><div class="trust-card"><b>Business Manager</b><p>${escapeHtml(bm.name||bm.id||'-')}</p></div></div>`;
}
function openMetaSettingsGuide(action='token'){
 const box=qs('#meta-settings-guide');if(!box)return;
 box.classList.remove('hidden');
 if(action==='token')setTimeout(()=>showMetaTokenBox('stable'),20);
 if(action==='accounts')setTimeout(()=>refreshSocialAccounts(),40);
 if(action==='assets')setTimeout(()=>discoverMetaAssets((state.config.setup_values||{}).ad_account_id||''),40);
 box.scrollIntoView({behavior:'smooth',block:'start'});
}
function renderMetaConnectionPanel(){
 const box=qs('#meta-connection-panel');if(!box)return;
 const v=state.config.setup_values||{};
 const tokenSet=Boolean(v.meta_access_token_set||v.meta_access_token_saved_at);
 const account=v.ad_account_id||'';
 const managed=v.managed_ad_accounts||state.managed_ad_accounts||{};
 const bm=managed.business_manager||{};
 const accountUse=`${managed.used||0}/${managed.max_accounts||5}`;
 const page=v.page_id||'';
 const instagram=v.instagram_actor_id||'';
 const savedAt=v.meta_access_token_saved_at?new Date(v.meta_access_token_saved_at).toLocaleString():'';
 const statusTitle=tokenSet?(lang==='es'?'Facebook conectado':'Facebook connected'):(lang==='es'?'Falta conectar Facebook':'Facebook needs connection');
 const statusBody=tokenSet?(lang==='es'?'Ya hay una clave de Meta guardada. Puedes agregar o cambiar entre hasta 5 cuentas publicitarias del mismo Business Manager.':'A Meta key is saved. You can add or switch between up to 5 ad accounts from the same Business Manager.'):(lang==='es'?'Pega la clave estable de tu propio Meta Business para que el dashboard pueda buscar tus cuentas reales.':'Paste the stable key from your own Meta Business so the dashboard can find your real accounts.');
 const onboardingOpen=qs('#onboarding-flow')?.classList.contains('open');
 const guide=onboardingOpen?'':`<div id="meta-settings-guide" class="meta-settings-guide ${tokenSet?'hidden':''}">${metaConnectionGuide()}</div>`;
 box.innerHTML=`<div class="next-step meta-connection-card"><div><b>${lang==='es'?'Conexión Facebook / Meta':'Facebook / Meta connection'}</b><p>${statusBody}</p>${savedAt?`<p class="notice">${lang==='es'?'Guardada':'Saved'}: ${escapeHtml(savedAt)}</p>`:''}</div><div class="mode-actions"><button class="btn ${tokenSet?'':'primary'}" type="button" data-action-code="openMetaSettingsGuide('token')">${tokenSet?(lang==='es'?'Cambiar clave de Facebook':'Change Facebook key'):(lang==='es'?'Conectar Facebook':'Connect Facebook')}</button><button class="btn" type="button" data-action-code="openMetaSettingsGuide('accounts')">${lang==='es'?'Buscar/agregar cuenta publicitaria':'Find/add ad account'}</button><button class="btn" type="button" ${account?'':'disabled'} data-action-code="openMetaSettingsGuide('assets')">${lang==='es'?'Buscar página e Instagram':'Find Page and Instagram'}</button></div></div><div class="trust-grid license-limits-grid"><div class="trust-card"><b>${lang==='es'?'Estado':'Status'}</b><p>${statusTitle}</p></div><div class="trust-card"><b>${lang==='es'?'Cuenta activa':'Active account'}</b><p>${escapeHtml(account||'-')}</p></div><div class="trust-card"><b>${lang==='es'?'Cuentas conectadas':'Connected accounts'}</b><p>${escapeHtml(accountUse)} ${lang==='es'?'máx. 5':'max 5'}</p></div><div class="trust-card"><b>Business Manager</b><p>${escapeHtml(bm.name||bm.id||'-')}</p></div><div class="trust-card"><b>${lang==='es'?'Página':'Page'}</b><p>${escapeHtml(page||'-')}</p></div><div class="trust-card"><b>Instagram</b><p>${escapeHtml(instagram||'-')}</p></div></div>${guide}`;
}
function renderSetupConfig(){
 const v=state.config.setup_values||{};
 const licensePlaceholder=v.license_key_set?(lang==='es'?'Licencia ya guardada. Pega una nueva solo si quieres cambiarla.':'License already saved. Paste a new one only to replace it.'):'MAO-...';
 qs('#setup-config').innerHTML=`<div class="next-step"><div><b>${t('setup_form_title')}</b><p>${t('setup_form_body')}</p></div><button class="btn ask-btn" type="button" data-action-code="openChat(lang==='es'?'Ayúdame a revisar estos datos de configuración y dime si falta algo importante.':'Help me review these setup details and tell me if anything important is missing.')">${t('ask_agent')}</button></div><form id="setup-config-form" class="form-grid">
  <div class="field"><label>${t('license_key')}</label><span class="field-help">${lang==='es'?'El código que recibiste al comprar.':'The code you received after purchase.'}</span><input name="license_key" value="" placeholder="${escapeHtml(licensePlaceholder)}"></div>
  <div class="field"><label>${t('buyer_email')}</label><span class="field-help">${lang==='es'?'El email usado para la compra o soporte.':'Email used for purchase or support.'}</span><input name="license_buyer_email" value="${escapeHtml(v.license_buyer_email||'')}" placeholder="buyer@email.com"></div>
  <div class="field wide"><label>${t('ad_account_id')}</label><span class="field-help">${lang==='es'?'Cuenta activa. Puedes conectar hasta 5 cuentas bajo el mismo Business Manager usando Buscar/agregar cuenta publicitaria.':'Active account. You can connect up to 5 accounts under the same Business Manager using Find/add ad account.'}</span><input name="ad_account_id" value="${escapeHtml(v.ad_account_id||'')}" placeholder="act_123456789"></div>
  <div class="field"><label>${t('page_id')}</label><span class="field-help">${lang==='es'?'La página desde donde salen tus anuncios.':'The Page your ads publish from.'}</span><input name="page_id" value="${escapeHtml(v.page_id||'')}"></div>
  <div class="field"><label>${t('instagram_actor_id')}</label><span class="field-help">${lang==='es'?'Solo si tu Instagram está conectado a la página.':'Only if Instagram is connected to the Page.'}</span><input name="instagram_actor_id" value="${escapeHtml(v.instagram_actor_id||'')}" placeholder="${lang==='es'?'opcional':'optional'}"></div>
  <div class="field"><label>${t('landing_url')}</label><span class="field-help">${lang==='es'?'La web a la que llegarán las personas.':'The website people will visit.'}</span><input name="landing_url" value="${escapeHtml(v.landing_url||'')}" placeholder="https://..."></div>
  <div class="field wide"><button class="btn primary" type="submit">${t('save_setup')}</button></div>
 </form>`;
 qs('#setup-config-form').addEventListener('submit',saveSetupConfig);
}
function renderPublishingPanel(){
 const box=qs('#publishing-panel');if(!box)return;
 const s=directPublishingState();
 box.innerHTML=`<div class="next-step meta-connection-card"><div><b>${s.title}</b><p>${s.body}</p>${s.savedAt?`<p class="notice">${lang==='es'?'Guardada':'Saved'}: ${escapeHtml(s.savedAt)}</p>`:''}</div><span class="badge ${s.ready?'ok':(s.tokenSet?'warn':'')}">${s.badge}</span></div>
 <div class="trust-grid license-limits-grid"><div class="trust-card"><b>${lang==='es'?'Página':'Page'}</b><p>${escapeHtml(s.page||'-')}</p></div><div class="trust-card"><b>${lang==='es'?'Uso':'Use'}</b><p>${lang==='es'?'Posts diarios, anuncios con post nativo y aprobación simple.':'Daily posts, native-post ads, and simple approval.'}</p></div><div class="trust-card"><b>${lang==='es'?'Privacidad':'Privacy'}</b><p><a href="https://admiraia.uboost.lat/privacy" target="_blank" rel="noopener noreferrer">admiraia.uboost.lat/privacy</a></p></div></div>${directPublishingGuide(false)}`;
}
function chatGptConnectMarkup(onboarding=false){
 const runtime=setupItem('hermes_runtime');
 const auth=setupItem('hermes_auth');
 const codex=setupItem('codex_cli');
 const model=state.config.agent_model||{};
 const studio=state.config.creative_studio||{};
 // Keep new installations on NVIDIA until the buyer explicitly chooses ChatGPT.
 const brain=model.brain_provider||'nvidia_nim';
 const apiBrain=['openai_api','minimax','nvidia_nim','custom_api'].includes(brain);
 const apiReady=apiBrain&&model.api_key_set&&Boolean(model.base_url)&&Boolean(model.model);
 const chatgptConnected=Boolean(model.chatgpt_connected);
 const chatgptReconnectRequired=Boolean(model.chatgpt_reauth_required);
 const chatgptReady=chatgptConnected&&brain==='openai_codex';
 const ready=chatgptReady||apiReady;
 const hermesMissing=runtime.status==='blocked';
 const title=ready?(lang==='es'?'Modelo del agente conectado':'Agent model connected'):(lang==='es'?'Conecta el cerebro del agente':'Connect the agent brain');
 const body=ready?(apiReady?(lang==='es'?`El manager ya puede pensar con ${model.model||'el modelo configurado'} sin perder memoria, herramientas ni aprobaciones.`:`The manager can now think with ${model.model||'the configured model'} while keeping memory, tools, and approvals.`):(lang==='es'?'El manager ya puede conversar usando tu sesion de ChatGPT/Codex. El chat, Telegram y las herramientas quedan sobre esta conexión.':'The manager can now talk through your ChatGPT/Codex session. Chat, Telegram, and agent tools use this connection.')):(onboarding?(lang==='es'?'Elige qué modelo usará el agente. Toca una opción y solo verás lo necesario.':'Choose which model the agent will use. Click an option and only the needed steps will open.'):(lang==='es'?'Elige cómo pensará el manager: NVIDIA NIM, OpenAI, tu suscripción de ChatGPT, MiniMax M3 u otra API compatible.':'Choose how the manager thinks: NVIDIA NIM, OpenAI, your ChatGPT subscription, MiniMax M3, or another compatible API.'));
 const badge=ready?(lang==='es'?'Listo':'Ready'):(hermesMissing?(lang==='es'?'Falta base del agente':'Agent base missing'):(lang==='es'?'Falta conectar':'Needs connection'));
 const detail=[runtime.detail,auth.detail,codex.detail].filter(Boolean).map(localText).join(' · ');
 const draft=lang==='es'?'Ayúdame a elegir el cerebro del agente. Explícame en palabras simples si me conviene ChatGPT/Codex, NVIDIA NIM, MiniMax M3 u otra API.':'Help me choose the agent brain. Explain simply whether ChatGPT/Codex, NVIDIA NIM, MiniMax M3, or another API is better for me.';
 const savedBase=model.base_url||'';
 const primaryRoute=brain==='openai_codex'?'chatgpt_subscription':(brain==='nvidia_nim'||savedBase.includes('api.nvidia.com')?'nvidia_nim':(brain==='minimax'||savedBase.includes('minimax')?'minimax_m3':(brain==='openai_api'||savedBase.includes('api.openai.com')?'openai_api':'custom_api')));
 const selectedRoute=primaryRoute;
 const connections=model.connections||{};
 const providerForRoute={openai_api:'openai_api',minimax_m3:'minimax',nvidia_nim:'nvidia_nim',custom_api:'custom_api'};
 const selectedConnection=connections[providerForRoute[selectedRoute]]||{};
 const telegramRuntime=model.telegram_runtime_model||{};
 const runtimeProvider=String(telegramRuntime.provider||'').toLowerCase().replace(/_/g,'-');
 const runtimeBase=String(telegramRuntime.base_url||'').toLowerCase();
 const runtimeRoute=(runtimeProvider.includes('nvidia')||runtimeBase.includes('api.nvidia.com'))?'nvidia_nim':(runtimeProvider.includes('minimax')?'minimax_m3':((runtimeProvider.includes('openai-codex')||runtimeProvider.includes('codex'))?'chatgpt_subscription':((runtimeProvider.includes('openai')||runtimeBase.includes('api.openai.com'))?'openai_api':(runtimeProvider.includes('custom')?'custom_api':''))));
 const runtimeModelLabel=telegramRuntime.label||[telegramRuntime.provider,telegramRuntime.model].filter(Boolean).join(' · ');
 const runtimeChanged=Boolean(runtimeModelLabel&&(telegramRuntime.source==='telegram_model_command'||telegramRuntime.is_configured_primary===false));
 const telegramRuntimeNotice=runtimeModelLabel?`<div class="telegram-runtime-note ${runtimeChanged?'changed':''}"><b>${lang==='es'?'Telegram ahora usa':'Telegram is using now'}</b><span>${escapeHtml(runtimeModelLabel)}</span>${runtimeChanged?`<small>${lang==='es'?'Cambiado desde Telegram con /model. Si quieres que sea el principal fijo, guárdalo aquí también.':'Changed from Telegram with /model. To make it the permanent primary model, save it here too.'}</small>`:''}</div>`:'';
 const base=selectedConnection.base_url||model.base_url||(selectedRoute==='nvidia_nim'?'https://integrate.api.nvidia.com/v1':(selectedRoute==='openai_api'?'https://api.openai.com/v1':(selectedRoute==='custom_api'?'':'https://api.minimax.io/v1')));
 const modelName=selectedConnection.model||model.model||(selectedRoute==='nvidia_nim'?'z-ai/glm-5.2':(selectedRoute==='openai_api'?'gpt-4.1-mini':(selectedRoute==='custom_api'?'':'MiniMax-M3')));
 const catalogVerified=Boolean(model.hermes_model_catalog_account_verified);
 const catalogAuthResolved=Boolean(model.hermes_model_catalog_auth_resolved);
 const imageSource=model.codex_image_source||studio.codex_image_source||'main_chatgpt';
 const imageDedicated=imageSource==='dedicated_chatgpt';
 const imageDedicatedAllowed=apiBrain;
 const imageReady=Boolean(studio.codex_image_ready||model.codex_image_ready);
 const imageSessionConnected=Boolean(studio.codex_image_connected||model.codex_image_connected);
 const imageConnected=imageDedicated?imageSessionConnected:chatgptConnected;
 const accountLabel=(account,connected)=>{const a=account||{};const label=a.email||a.label||'';if(label)return escapeHtml(label);return connected?(lang==='es'?'Cuenta conectada · email no visible por Codex':'Connected account · email not exposed by Codex'):(lang==='es'?'Sin cuenta conectada':'No connected account')};
 const mainAccountLabel=accountLabel(model.chatgpt_account,chatgptConnected);
 const imageAccountLabel=accountLabel(model.codex_image_account||studio.codex_image_account,imageConnected);
 const imageStatusText=imageDedicated
  ? (imageConnected?(lang==='es'?'Image 2 listo con cuenta separada':'Image 2 ready with separate account'):(lang==='es'?'Cuenta de imágenes pendiente':'Image account pending'))
  : (chatgptConnected?(lang==='es'?'Image 2 usa la cuenta principal de ChatGPT':'Image 2 uses the main ChatGPT account'):(lang==='es'?'Image 2 necesita una cuenta ChatGPT conectada':'Image 2 needs a connected ChatGPT account'));
 const api=selectedConnection.api||model.api||'openai-chat-completions';
 const keyPlaceholder=selectedConnection.api_key_set?(lang==='es'?'Clave guardada. Pega otra solo si quieres cambiarla.':'Key saved. Paste another only to replace it.'):(lang==='es'?'Pega la clave API del proveedor':'Paste the provider API key');
 const routeCopy={
  openai_api:{icon:'OA',title:lang==='es'?'OpenAI API':'OpenAI API',desc:lang==='es'?'Si tienes una clave API de OpenAI.':'If you have an OpenAI API key.',panel:lang==='es'?'Pega tu clave API de OpenAI. El agente seguirá usando su memoria, herramientas y aprobaciones.':'Paste your OpenAI API key. The agent still keeps its memory, tools, and approvals.'},
  chatgpt_subscription:{icon:'CG',title:lang==='es'?'ChatGPT suscripción':'ChatGPT subscription',desc:lang==='es'?'Requiere ChatGPT Plus o superior · Luna automático.':'Requires ChatGPT Plus or higher · Luna automatic.',panel:lang==='es'?'Solo se puede conectar una suscripción Plus o superior; las cuentas Free no sirven como cerebro principal. Primero, en ChatGPT abre Ajustes > Seguridad y activa el login por código para Codex. Después toca Conectar ahora; Luna se elegirá automáticamente.':'Only a Plus-or-higher subscription can be connected; Free accounts cannot be the primary brain. First, in ChatGPT open Settings > Security and enable device-code login for Codex. Then click Connect now; Luna will be selected automatically.'},
  minimax_m3:{icon:'M3',title:'MiniMax M3',desc:lang==='es'?'Con clave de MiniMax.':'With a MiniMax key.',panel:lang==='es'?'Pega tu clave de MiniMax. Ya dejé URL y modelo listos para M3. El agente seguirá usando su memoria y herramientas.':'Paste your MiniMax key. URL and model are already set for M3. The agent still keeps memory and tools.'},
  nvidia_nim:{icon:'NV',title:'NVIDIA NIM',desc:lang==='es'?'Modelos alojados del API Catalog.':'Hosted API Catalog models.',panel:lang==='es'?'Pega una API key de build.nvidia.com y carga la lista actual de modelos. El acceso alojado está sujeto a las cuotas y límites de NVIDIA.':'Paste an API key from build.nvidia.com and load the current model list. Hosted access is subject to NVIDIA quotas and limits.'},
  custom_api:{icon:'{}',title:lang==='es'?'Otra API compatible':'Other compatible API',desc:lang==='es'?'Para proveedores tipo OpenAI.':'For OpenAI-style providers.',panel:lang==='es'?'Pega la URL, el nombre del modelo y la clave del proveedor. El agente la usará como cerebro.':'Paste the provider URL, model name, and key. The agent will use it as its brain.'}
 };
 const routeConnected={chatgpt_subscription:chatgptConnected,openai_api:Boolean(connections.openai_api?.configured),minimax_m3:Boolean(connections.minimax?.configured),nvidia_nim:Boolean(connections.nvidia_nim?.configured),custom_api:Boolean(connections.custom_api?.configured)};
 const routeButton=kind=>{const primary=primaryRoute===kind;const selected=selectedRoute===kind;const connected=Boolean(routeConnected[kind]);const runtimeActive=Boolean(runtimeRoute===kind&&runtimeModelLabel&&!primary);const routeState=primary?(lang==='es'?'Principal':'Primary'):(runtimeActive?(lang==='es'?'En uso en Telegram':'In use on Telegram'):(connected?(lang==='es'?'Conectado':'Connected'):''));return `<button class="agent-model-option ${selected?'active':''} ${primary?'primary-route':''} ${(connected||runtimeActive)?'connected':''}" type="button" data-agent-route="${kind}" aria-expanded="${selected?'true':'false'}" data-action-code="selectAgentModelRoute('${kind}')"><span class="route-icon">${routeCopy[kind].icon}</span><span><b>${routeCopy[kind].title}</b><p>${routeCopy[kind].desc}</p>${routeState?`<em class="route-state">${routeState}</em>`:''}</span></button>`};
 const apiPanelTitle=selectedRoute==='chatgpt_subscription'?routeCopy.minimax_m3.title:routeCopy[selectedRoute].title;
 const apiPanelHelp=selectedRoute==='chatgpt_subscription'?routeCopy.minimax_m3.panel:routeCopy[selectedRoute].panel;
 const providerValue=providerForRoute[selectedRoute]||'openai_codex';
 const liveNvidiaModels=(Array.isArray(model.nvidia_model_options)?model.nvidia_model_options:[]).map(value=>String(value||'').trim()).filter(Boolean);
 const recommendedNvidiaModel=String(model.nvidia_model_recommended||'z-ai/glm-5.2').trim();
 const nvidiaModels=liveNvidiaModels.length?[...liveNvidiaModels]:[recommendedNvidiaModel];
 if(selectedRoute==='nvidia_nim'&&modelName&&!nvidiaModels.includes(modelName))nvidiaModels.unshift(modelName);
 const nvidiaModelOptions=nvidiaModels.map(value=>`<option value="${escapeHtml(value)}">${escapeHtml(value===recommendedNvidiaModel?(lang==='es'?'Recomendado':'Recommended'):'')}</option>`).join('');
 const apiModelField=`<input name="agent_chat_model" value="${escapeHtml(modelName)}" placeholder="${lang==='es'?'Nombre del modelo':'Model name'}" ${selectedRoute==='nvidia_nim'?'list="nvidia-model-options"':''}><datalist id="nvidia-model-options">${nvidiaModelOptions}</datalist>`;
 const nvidiaCatalogAction=selectedRoute==='nvidia_nim'?`<button class="btn" type="button" data-action-code="refreshNvidiaModelCatalog(event)">${lang==='es'?'Cargar modelos de NVIDIA':'Load NVIDIA models'}</button><a class="btn" href="https://build.nvidia.com/" target="_blank" rel="noopener noreferrer">${lang==='es'?'Obtener API key':'Get API key'}</a>`:'';
 const liveCodexModels=(Array.isArray(model.hermes_model_options)?model.hermes_model_options:[]).map(value=>String(value||'').trim()).filter(Boolean);
 const configuredCodexModel=String(model.hermes_model||'').trim();
 const userSelectedCodexModel=Boolean(model.hermes_model_user_selected);
 const recommendedCodexModelFromCatalog=String(model.hermes_model_recommended||liveCodexModels[0]||'').trim();
 const preferredCodexModel='gpt-5.6-luna';
 const codexModel=catalogVerified
  ? (userSelectedCodexModel&&liveCodexModels.includes(configuredCodexModel)?configuredCodexModel:(liveCodexModels.includes(preferredCodexModel)?preferredCodexModel:(liveCodexModels.includes(recommendedCodexModelFromCatalog)?recommendedCodexModelFromCatalog:liveCodexModels[0]||'')))
  : (userSelectedCodexModel?(configuredCodexModel||recommendedCodexModelFromCatalog):preferredCodexModel);
 if(!catalogVerified&&codexModel&&!liveCodexModels.includes(codexModel))liveCodexModels.unshift(codexModel);
 if(!liveCodexModels.length)liveCodexModels.push(codexModel||'gpt-5.4-mini');
 const recommendedCodexModel=String(model.hermes_model_recommended||liveCodexModels[0]||'').trim();
 const codexModelOptions=liveCodexModels.map(value=>`<option value="${escapeHtml(value)}" ${codexModel===value?'selected':''}>${escapeHtml(value+(value===preferredCodexModel?(lang==='es'?' · Luna automático': ' · Luna automatic'):(value===recommendedCodexModel?(lang==='es'?' · recomendado':' · recommended'):'')))}</option>`).join('');
 const runtimeVersions=model.runtime_versions||{};
 const catalogHas56=liveCodexModels.some(value=>/^gpt-5\.6(?:[-.:]|$)/i.test(value));
 const catalogStateNote=catalogVerified
  ? (catalogHas56
    ? (lang==='es'?'Lista verificada con esta cuenta; muestra los modelos que realmente puede usar.':'Verified with this account; showing the models it can actually use.')
    : (lang==='es'?'Lista verificada con esta cuenta: GPT‑5.6 no aparece como disponible para esta cuenta o plan.':'Verified with this account: GPT‑5.6 is not available to this account or plan.'))
  : (catalogAuthResolved
    ? (lang==='es'?'No pude validar todavía el catálogo de esta cuenta; muestro la última lista conocida. Actualiza después de conectar.':'I could not validate this account catalog yet; showing the last known list. Refresh after connecting.')
    : (lang==='es'?'Catálogo provisional: conecta o actualiza para confirmar los modelos disponibles en tu cuenta.':'Provisional catalog: connect or refresh to confirm the models available to your account.'));
 const runtimeVersionNote=`<p class="notice">${catalogStateNote}${runtimeVersions.hermes?` Hermes: ${escapeHtml(runtimeVersions.hermes)}`:''}${runtimeVersions.codex?` · Codex: ${escapeHtml(runtimeVersions.codex)}`:''}</p>`;
 const chatgptSettingsButton=`<a class="btn chatgpt-settings-link" href="https://chatgpt.com/#settings/Security" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir configuración de ChatGPT':'Open ChatGPT settings'}</a>`;
 const chatgptActions=chatgptConnected
  ? `<button class="btn ${chatgptReady?'':'primary'}" type="button" data-action-code="saveChatGptModel(event)">${chatgptReady?(lang==='es'?'Guardar modelo':'Save model'):(lang==='es'?'Usar como principal':'Use as primary')}</button><button class="btn danger" type="button" data-action-code="disconnectAgentModel('agent')">${lang==='es'?'Desconectar para cambiar cuenta':'Disconnect to change account'}</button>`
  : `<button class="btn primary" type="button" data-action-code="connectChatGpt(event)">${lang==='es'?'Ya lo hice, conectar a ChatGPT ahora':'I did it, connect to ChatGPT now'}</button>`;
 const chatgptReconnectNotice=chatgptReconnectRequired?`<div class="guide-card chatgpt-settings-help"><b>${lang==='es'?'La sesión de ChatGPT venció':'The ChatGPT session expired'}</b><p>${lang==='es'?'La cuenta puede seguir funcionando normalmente en otros dispositivos, pero esta instalación necesita una autorización nueva. Vuelve a conectarla aquí; tu memoria y trabajo guardado no se pierden.':'The account may still work normally on other devices, but this installation needs a new authorization. Reconnect it here; your saved memory and work are safe.'}</p></div>`:'';
 const imagePrimaryNote=!imageDedicated&&chatgptConnected?`<p class="notice">${lang==='es'?'Image 2 usa la misma cuenta ChatGPT/Codex del cerebro principal. Para cambiarla, desconecta y conecta otra cuenta en la tarjeta principal.':'Image 2 uses the same ChatGPT/Codex account as the primary brain. To change it, disconnect and connect a different account in the main card.'}</p>`:'';
 const imageConnectLabel=imageDedicated?(lang==='es'?'Conectar cuenta de imágenes':'Connect image account'):(lang==='es'?'Conectar otra cuenta para Image 2':'Connect another account for Image 2');
 const imageConnectButton=imageDedicatedAllowed&&(!imageDedicated||!imageConnected)?`<button class="btn ${imageConnected?'':'primary'}" type="button" data-action-code="connectImageChatGpt(event)">${imageConnectLabel}</button>`:'';
 const imageDisconnectButton=imageDedicated&&imageConnected?`<button class="btn danger" type="button" data-action-code="disconnectAgentModel('image')">${lang==='es'?'Desconectar imágenes':'Disconnect images'}</button>`:'';
 const imageChatgptCard=`<div class="image-chatgpt-card ${imageConnected?'ready':''}">
  <div><b>${lang==='es'?'Image 2 con ChatGPT/Codex':'Image 2 with ChatGPT/Codex'}</b><p>${lang==='es'?'Image 2 siempre usa Codex. Si el texto del agente usa MiniMax u otra API, puedes conectar una cuenta ChatGPT distinta solo para generar creativos.':'Image 2 always uses Codex. If the text agent uses MiniMax or another API, you can connect a different ChatGPT account only for creative generation.'}</p><span class="badge ${imageConnected?'ok':'warn'}">${imageStatusText}</span><div class="connected-account"><b>${lang==='es'?'Cuenta':'Account'}</b><span>${imageAccountLabel}</span></div>${imagePrimaryNote}</div>
  <input type="hidden" name="codex_image_source" value="${escapeHtml(imageSource)}"><input type="hidden" name="codex_image_hermes_model" value="gpt-5.5">
  <div id="image-chatgpt-connect-result" class="chatgpt-connect-result hidden"></div>
  <div class="agent-route-actions">${imageConnectButton}${imageDisconnectButton}</div>
 </div>`;
 return `<section class="chatgpt-connect-card ${ready?'ready':''}"><div class="chatgpt-connect-head"><div><h3>${title}</h3><p>${body}</p></div><span class="badge ${ready?'ok':'warn'}">${badge}</span></div><div class="agent-model-picker" role="tablist" aria-label="${lang==='es'?'Opciones de modelo del agente':'Agent model options'}">${routeButton('nvidia_nim')}${routeButton('openai_api')}${routeButton('chatgpt_subscription')}${routeButton('minimax_m3')}${routeButton('custom_api')}</div>${telegramRuntimeNotice}<form id="agent-model-form" class="model-provider-form" data-submit-code="saveSetupConfig(event)">
 <input type="hidden" name="agent_chat_provider" value="${escapeHtml(providerValue)}">
 <input type="hidden" name="agent_chat_api" value="${escapeHtml(api)}">
 <div class="agent-route-panels">
  <div class="agent-route-panel ${selectedRoute==='chatgpt_subscription'?'active':''}" data-agent-route-panel="chatgpt_subscription"><h4>${routeCopy.chatgpt_subscription.title}</h4><p>${routeCopy.chatgpt_subscription.panel}</p>${chatgptReconnectNotice}<div class="chatgpt-preflight"><b>${chatgptConnected?(chatgptReady?(lang==='es'?'Conectado y principal':'Connected and primary'):(lang==='es'?'Conectado, no principal':'Connected, not primary')):(lang==='es'?'Antes de conectar':'Before connecting')}</b><div class="connected-account"><b>${lang==='es'?'Cuenta':'Account'}</b><span>${mainAccountLabel}</span></div><ol><li>${lang==='es'?'Usa el modelo marcado como recomendado; la lista se actualiza desde ChatGPT/Hermes.':'Use the model marked as recommended; the list refreshes from ChatGPT/Hermes.'}</li>${chatgptConnected?'':`<li>${lang==='es'?'Toca el botón de abajo para abrir la configuración de tu cuenta ChatGPT.':'Click the button below to open your ChatGPT account settings.'}</li><li>${lang==='es'?'Entra a Seguridad, ve al final y activa “Activar autorización con códigos de dispositivo para Codex”.':'Open Security, go to the bottom, and turn on “Enable device code authorization for Codex”.'}</li><li>${lang==='es'?'Vuelve aquí y toca el botón “Ya lo hice, conectar a ChatGPT ahora”.':'Come back here and click “I did it, connect to ChatGPT now”.'}</li>`}</ol>${chatgptConnected?'':`<div class="chatgpt-settings-actions">${chatgptSettingsButton}</div>`}</div><div class="form-grid codex-model-choice"><div class="field wide"><label>${lang==='es'?'Modelo para ChatGPT/Codex':'ChatGPT/Codex model'}</label><span class="field-help">${lang==='es'?'Modelos disponibles para esta instalación/cuenta.':'Models available for this installation/account.'}</span><select name="hermes_model">${codexModelOptions}</select></div></div>${runtimeVersionNote}<div class="agent-route-actions">${chatgptActions}<button class="btn" type="button" data-action-code="refreshCodexModelCatalog(event)">${lang==='es'?'Actualizar lista de modelos':'Refresh model list'}</button></div><div id="chatgpt-connect-result" class="chatgpt-connect-result hidden"></div></div>
  <div class="agent-route-panel ${selectedRoute!=='chatgpt_subscription'?'active':''}" data-agent-route-panel="api"><h4 id="agent-api-route-title">${apiPanelTitle}</h4><p id="agent-api-route-help">${apiPanelHelp}</p><div class="form-grid">
   <div class="field"><label>${lang==='es'?'Modelo':'Model'}</label>${apiModelField}</div>
   <div class="field"><label>${lang==='es'?'URL compatible OpenAI':'OpenAI-compatible URL'}</label><span class="field-help">${selectedRoute==='nvidia_nim'?(lang==='es'?'Endpoint oficial fijo de NVIDIA NIM.':'Fixed official NVIDIA NIM endpoint.'):(lang==='es'?'Debe usar https://. Solo se permite http:// para modelos locales como 127.0.0.1.':'Must use https://. http:// is allowed only for local models such as 127.0.0.1.')}</span><input name="agent_chat_base_url" value="${escapeHtml(base)}" placeholder="https://api.ejemplo.com/v1" ${selectedRoute==='nvidia_nim'?'readonly':''}></div>
   <div class="field wide"><label>${lang==='es'?'Clave API del modelo':'Model API key'}</label><span class="field-help">${lang==='es'?'Se guarda dentro de este PC/VPS. No aparece de vuelta en el dashboard.':'Stored on this PC/VPS. It is never shown back in the dashboard.'}</span><input type="password" name="agent_chat_api_key" value="" placeholder="${escapeHtml(keyPlaceholder)}"></div>
   <div class="field wide"><div class="agent-route-actions"><button id="save-agent-connection" class="btn" type="submit" name="agent_model_action" value="save_connection">${lang==='es'?'Guardar conexión':'Save connection'}</button><button id="set-agent-primary" class="btn primary" type="submit" name="agent_model_action" value="set_primary">${primaryRoute===selectedRoute?(lang==='es'?'Ya es principal':'Already primary'):(lang==='es'?'Usar como principal':'Use as primary')}</button>${nvidiaCatalogAction}</div></div>
  </div></div>
 </div>
 ${imageChatgptCard}
 </form><details class="helper-command"><summary>${lang==='es'?'Ver diagnóstico para soporte':'Show support diagnostics'}</summary><span class="step-command">${escapeHtml(detail||'-')}</span></details><div class="chatgpt-foot"><div></div><div class="mode-actions"><button class="btn primary chatgpt-recheck-main" type="button" data-action-code="load()">${lang==='es'?'Ya lo hice, revisar conexión':'I did it, recheck'}</button></div></div></section>`;
}
function renderChatGptPanel(){
 qs('#chatgpt-panel').innerHTML=chatGptConnectMarkup(false);
 const modelChoice=qs('#chatgpt-panel .codex-model-choice');
 if(modelChoice&&!state.config?.agent_model?.chatgpt_connected)modelChoice.classList.add('hidden');
}
const TELEGRAM_GUIDE_VIDEO='/assets/tutorial-meta/crear-bot-telegram.mp4';
const TELEGRAM_GUIDE_VIDEO_FALLBACK='/assets/tutorial-meta/crear-bot-telegram.mov';
let telegramAutoSaveTimer=null;
let telegramAutoSaveLast='';
function telegramVideoMarkup(){
 return `<div class="telegram-video-card"><div class="telegram-video-copy"><span class="guide-eyebrow">${lang==='es'?'Video corto':'Short video'}</span><b>${lang==='es'?'Mira cómo se crea el bot':'Watch how to create the bot'}</b><p>${lang==='es'?'Dale play y sigue el ejemplo. El video muestra BotFather, /newbot y dónde copiar la clave larga.':'Press play and follow the example. The video shows BotFather, /newbot, and where to copy the long key.'}</p></div><div class="telegram-video-frame"><video class="telegram-setup-video" controls playsinline preload="metadata"><source src="${TELEGRAM_GUIDE_VIDEO}" type="video/mp4"><source src="${TELEGRAM_GUIDE_VIDEO_FALLBACK}" type="video/quicktime"></video></div></div>`;
}
function telegramTokenSavedInline(){
 return `<div class="telegram-token-saved-inline" data-telegram-saved-card><div><b>${lang==='es'?'Clave guardada':'Key saved'}</b><p>${lang==='es'?'Ahora abre el bot que creaste en Telegram, envíale "hola" y toca el botón grande para detectar tu chat. Después te enviaré el primer mensaje automáticamente.':'Now open the bot you created in Telegram, send "hello", and tap the big button to detect your chat. Then I will send the first message automatically.'}</p></div><button class="btn primary telegram-detect-button" type="button" data-action-code="detectTelegramChats()">${lang==='es'?'Ya envié hola, detectar mi chat':'I sent hello, detect my chat'}</button></div>`;
}
function telegramStatusMarkup(value={}){
 const v=value||{};
 const ready=Boolean(v.enabled&&v.bot_configured&&v.chat_id);
 if(ready)return `<div class="telegram-next-action ready"><div class="telegram-orb">✓</div><div><b>${lang==='es'?'Telegram listo':'Telegram ready'}</b><p>${lang==='es'?'Ya puedes hablar con el manager desde tu celular. También podrá mostrarte aprobaciones con botones seguros.':'You can now talk with the manager from your phone. It can also show approval buttons safely.'}</p></div></div>`;
 if(v.bot_configured)return `<div class="telegram-next-action"><div class="telegram-orb">AI</div><div><b>${lang==='es'?'Clave guardada':'Key saved'}</b><p>${lang==='es'?'Ahora envía un "hola" al bot que creaste. Después vuelve aquí, detecto tu chat y te envío el primer mensaje.':'Now send "hello" to the bot you created. Then come back here, I will detect your chat and send the first message.'}</p></div><button class="btn primary telegram-detect-button" type="button" data-action-code="detectTelegramChats()">${lang==='es'?'Ya envié hola, detectar mi chat':'I sent hello, detect my chat'}</button></div>`;
 return `<div class="guide-card telegram-wait-card"><b>${lang==='es'?'Pega la clave larga':'Paste the long key'}</b><p>${lang==='es'?'Cuando la pegues completa, la guardaré automáticamente y te diré el siguiente paso.':'When you paste it complete, I will save it automatically and show the next step.'}</p></div>`;
}
function telegramTokenLooksValid(token){return /^\d{5,}:[A-Za-z0-9_-]{20,}$/.test(String(token||'').trim())}
function telegramConfigPayloadFromForm(form,tokenValue){
 const data=Object.fromEntries(new FormData(form).entries());
 if(tokenValue!==undefined)data.bot_token=tokenValue;
 data.enabled=form.enabled?form.enabled.checked:true;
 return data;
}
function telegramStatusFromResponse(response){
 const status=response?.result&&typeof response.result==='object'?response.result:response;
 return status&&typeof status==='object'?status:{};
}
function setTelegramTokenZone(input,stateName,message=''){
 const zone=input?.closest?.('.telegram-token-zone');if(!zone)return;
 zone.classList.remove('saving','saved','invalid');
 if(stateName)zone.classList.add(stateName);
 const help=zone.querySelector('[data-telegram-token-help]');
 if(help&&message)help.textContent=message;
 if(stateName==='saved'&&!qs('.activation-shell')&&!zone.querySelector('[data-telegram-saved-card]'))zone.insertAdjacentHTML('beforeend',telegramTokenSavedInline());
 if(stateName==='saved')setTimeout(()=>zone.querySelector('.telegram-detect-button')?.scrollIntoView({behavior:'smooth',block:'center'}),80);
}
async function autoSaveTelegramToken(event){
 const input=event?.target;const form=input?.closest?.('form');if(!input||!form)return;
 if(event?.type==='paste'){setTimeout(()=>autoSaveTelegramToken({target:input}),0);return}
 const token=String(input.value||'').trim();
 clearTimeout(telegramAutoSaveTimer);
 if(!token){setTelegramTokenZone(input,'',lang==='es'?'Pega la clave larga de BotFather. La guardaré sola.':'Paste the long BotFather key. I will save it automatically.');return}
 if(!telegramTokenLooksValid(token)){setTelegramTokenZone(input,'invalid',lang==='es'?'Sigue pegando la clave completa. Debe tener números, dos puntos y muchas letras.':'Keep pasting the complete key. It should have numbers, a colon, and many letters.');return}
 if(token===telegramAutoSaveLast&&(state.config?.telegram_agent||{}).bot_configured){setTelegramTokenZone(input,'saved',lang==='es'?'Clave guardada. Ahora envía un "hola" al bot.':'Key saved. Now send "hello" to the bot.');return}
 setTelegramTokenZone(input,'saving',lang==='es'?'Guardando la clave en esta instalación...':'Saving the key in this install...');
 telegramAutoSaveTimer=setTimeout(async()=>{
  try{
	   const response=await api('/api/telegram/config',{method:'POST',body:JSON.stringify(telegramConfigPayloadFromForm(form,token))});
	   const status=telegramStatusFromResponse(response);
   telegramAutoSaveLast=token;
   state.config.telegram_agent={...(state.config.telegram_agent||{}),...status};
   input.value='';
   input.placeholder=lang==='es'?'Clave guardada. Pega otra solo si quieres cambiarla.':'Key saved. Paste another only if you want to replace it.';
   setTelegramTokenZone(input,'saved',lang==='es'?'Clave guardada. Ahora envía un "hola" al bot que creaste.':'Key saved. Now send "hello" to the bot you created.');
   const box=qs('#telegram-results');if(box)box.innerHTML=qs('.activation-shell')?compactTelegramStatusMarkup(state.config.telegram_agent):telegramStatusMarkup(state.config.telegram_agent);
   toast(lang==='es'?'Clave guardada. Ahora envía "hola" al bot.':'Key saved. Now send "hello" to the bot.');
   startTelegramHelloPolling();
  }catch(err){
   setTelegramTokenZone(input,'invalid',err.message||String(err));
   const box=qs('#telegram-results');if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude guardar la clave':'Could not save the key'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;
  }
 },650);
}
async function autoSaveTelegramSetting(event){
 const form=event?.target?.closest?.('form');if(!form)return;
 const data=telegramConfigPayloadFromForm(form);
 if(!String(data.bot_token||'').trim())delete data.bot_token;
 try{const response=await api('/api/telegram/config',{method:'POST',body:JSON.stringify(data)});const status=telegramStatusFromResponse(response);state.config.telegram_agent={...(state.config.telegram_agent||{}),...status};const box=qs('#telegram-results');if(box)box.innerHTML=qs('.activation-shell')?compactTelegramStatusMarkup(state.config.telegram_agent):telegramStatusMarkup(state.config.telegram_agent);startTelegramHelloPolling()}catch(err){toast(err.message||String(err))}
}
function telegramOnboardingGuide(){
 const v=state.config.telegram_agent||{};
 const checked=v.enabled||!v.bot_configured?'checked':'';
 const tokenState=v.bot_configured?'saved':'';
 if(lang==='es')return `<div class="setup-guide private-connection telegram-onboarding"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Celular</span><h3>Habla con tu manager por Telegram</h3><p>Recomendado: podrás escribirle al agente desde tu celular, enviar imágenes y aprobar decisiones exactas con botones. Esto se configura una sola vez.</p><div class="guide-actions"><a class="btn primary" href="https://telegram.org/dl" target="_blank" rel="noopener noreferrer">Descargar Telegram</a><a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">Abrir BotFather</a><button class="btn" type="button" data-action-code="copyCommand('/newbot')">Copiar /newbot</button></div></div><aside class="guide-checklist"><b>Pasos simples</b><ol><li>Instala Telegram en tu celular. Si puedes, también en tu PC para copiar más fácil.</li><li>Busca <b>BotFather</b> y escribe <b>/newbot</b>.</li><li>Ponle cualquier nombre a tu bot.</li><li>Elige un usuario que termine en <b>bot</b>.</li><li>Copia la clave larga de BotFather y pégala abajo.</li></ol></aside></section>${telegramVideoMarkup()}<form class="onboarding-mini two telegram-token-form"><label class="wide telegram-token-zone ${tokenState}">Clave larga que te dio BotFather<span class="field-help" data-telegram-token-help>${v.bot_configured?'Clave guardada. Pega otra solo si quieres cambiarla.':'Pégala completa. La guardaré automáticamente en este PC/VPS.'}</span>${v.bot_configured?telegramTokenSavedInline():''}<input type="password" name="bot_token" value="" data-input-code="autoSaveTelegramToken(event)" data-paste-code="autoSaveTelegramToken(event)" autocomplete="off" placeholder="${v.bot_configured?'Clave guardada. Pega otra solo si quieres cambiarla.':'Pega aquí la clave larga de BotFather'}"></label><label>Idioma del manager<select name="language" data-change-code="autoSaveTelegramSetting(event)"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></label><label><input type="checkbox" name="enabled" ${checked} data-change-code="autoSaveTelegramSetting(event)"> Activar Telegram</label></form><div id="telegram-results" class="setup-guide">${telegramStatusMarkup(v)}</div><details class="fallback-details"><summary>Lo puedo hacer después</summary><p class="notice">Puedes seguir ahora y volver a este paso desde Configuración. Para usar Telegram, el dashboard debe estar encendido en tu PC/VPS.</p></details></div>`;
 return `<div class="setup-guide private-connection telegram-onboarding"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Phone</span><h3>Talk to your manager through Telegram</h3><p>Recommended: message the agent from your phone, send images, and approve exact decisions with buttons. You do this once.</p><div class="guide-actions"><a class="btn primary" href="https://telegram.org/dl" target="_blank" rel="noopener noreferrer">Download Telegram</a><a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">Open BotFather</a><button class="btn" type="button" data-action-code="copyCommand('/newbot')">Copy /newbot</button></div></div><aside class="guide-checklist"><b>Simple steps</b><ol><li>Install Telegram on your phone. If possible, also install it on your PC.</li><li>Search <b>BotFather</b> and send <b>/newbot</b>.</li><li>Give your bot any name.</li><li>Choose a username that ends in <b>bot</b>.</li><li>Copy BotFather's long key and paste it below.</li></ol></aside></section>${telegramVideoMarkup()}<form class="onboarding-mini two telegram-token-form"><label class="wide telegram-token-zone ${tokenState}">Long key from BotFather<span class="field-help" data-telegram-token-help>${v.bot_configured?'Key saved. Paste another only to replace it.':'Paste it complete. I will save it automatically on this PC/VPS.'}</span>${v.bot_configured?telegramTokenSavedInline():''}<input type="password" name="bot_token" value="" data-input-code="autoSaveTelegramToken(event)" data-paste-code="autoSaveTelegramToken(event)" autocomplete="off" placeholder="${v.bot_configured?'Key saved. Paste another only to replace it.':'Paste the long BotFather key here'}"></label><label>Manager language<select name="language" data-change-code="autoSaveTelegramSetting(event)"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></label><label><input type="checkbox" name="enabled" ${checked} data-change-code="autoSaveTelegramSetting(event)"> Enable Telegram</label></form><div id="telegram-results" class="setup-guide">${telegramStatusMarkup(v)}</div><details class="fallback-details"><summary>I can do this later</summary><p class="notice">You can continue now and come back from Setup. To use Telegram, the dashboard must be running on your PC/VPS.</p></details></div>`;
}
function communicationStyleGuide(onboarding=false){
 const saved=state.config?.communication_preference?.configured?String(state.config?.communication_preference?.style||'').toLowerCase():'';
 const effectiveStyle=saved||(onboarding?'simple':'');
 const simpleChecked=effectiveStyle==='simple'?'checked':'';
 const technicalChecked=saved==='technical'?'checked':'';
 const submitCode='saveCommunicationStyle(event,false)';
 const title=lang==='es'?'Último detalle: ¿simple o técnico?':'Last detail: simple or technical?';
 const body=lang==='es'?'Elige cómo quieres que el agente te explique las cosas. Puedes cambiarlo después.':'Choose how the agent should explain things. You can change this later.';
 const note=onboarding?'':`<p class="notice">${lang==='es'?'Es una preferencia global para chat y Telegram.':'This is a global preference for chat and Telegram.'}</p>`;
 return `<form class="communication-style-form" data-submit-code="${submitCode}"><fieldset><legend>${title}</legend><p>${body}</p><div class="communication-style-grid"><label class="communication-style-option"><input type="radio" name="communication_style" value="simple" required ${simpleChecked}><span><b>${lang==='es'?'Palabras simples':'Simple words'}</b><small>${lang==='es'?'Directo, claro y sin jerga.':'Direct, clear, no jargon.'}</small><em>${lang==='es'?'Recomendado':'Recommended'}</em></span></label><label class="communication-style-option"><input type="radio" name="communication_style" value="technical" required ${technicalChecked}><span><b>${lang==='es'?'Explicaciones técnicas':'Technical explanations'}</b><small>${lang==='es'?'Más detalle cuando ayude a decidir.':'More detail when it helps decisions.'}</small><em>${lang==='es'?'Para usuarios con experiencia':'For experienced users'}</em></span></label></div>${note}<div class="onboarding-step-actions"><button class="btn primary" type="submit">${lang==='es'?'Guardar forma de hablar':'Save communication style'}</button></div></fieldset></form>`;
}
async function saveCommunicationStyle(event,finish=false){
 event.preventDefault();
 const form=event.target;
 const preferenceValue=String(new FormData(form).get('communication_style')||'').trim().toLowerCase();
 if(!['simple','technical'].includes(preferenceValue)){toast(lang==='es'?'Elige una de las dos formas de hablar.':'Choose one communication style.');return}
 if(finish){await finishOnboardingAndStartTour('communication',preferenceValue);return}
 await api('/api/onboarding/communication-style',{method:'POST',body:JSON.stringify({communication_style:preferenceValue,language:lang})});
 toast(lang==='es'?'Forma de hablar guardada.':'Communication style saved.');
 await load();
}
let chatGptConnectPollTimer=null;
let chatGptConnectPurpose='agent';
let chatGptConnectTarget='chatgpt-connect-result';
let chatGptAuthWindow=null;
let chatGptAuthOpenedUrl='';
function chatGptAuthWaitingHtml(title,body,kind='waiting'){
 const safeKind=String(kind||'waiting').replace(/[^a-z0-9_-]/gi,'')||'waiting';
 const action=safeKind==='error'?`<a class="btn" href="/dashboard">${lang==='es'?'Volver al dashboard':'Return to dashboard'}</a>`:'';
 return `<!doctype html><html><head><title>Admira IA</title><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/dashboard/login-wait.css?v=1"></head><body class="${safeKind}"><div class="card"><div class="dot"></div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(body)}</p>${action}</div></body></html>`;
}
function updateChatGptAuthWindow(title,body,kind='waiting'){
 try{
  if(!chatGptAuthWindow||chatGptAuthWindow.closed||chatGptAuthOpenedUrl)return false;
  chatGptAuthWindow.document.open();
  chatGptAuthWindow.document.write(chatGptAuthWaitingHtml(title,body,kind));
  chatGptAuthWindow.document.close();
  return true;
 }catch(_err){return false}
}
function prepareChatGptAuthWindow(){
 try{
  chatGptAuthOpenedUrl='';
  chatGptAuthWindow=window.open('about:blank','admira_chatgpt_login');
  if(!chatGptAuthWindow)return false;
  updateChatGptAuthWindow(
   lang==='es'?'Preparando login':'Preparing login',
   lang==='es'?'Estoy buscando el enlace seguro de ChatGPT/Codex. Esta pestaña se abrirá sola cuando esté listo.':'I am finding the secure ChatGPT/Codex link. This tab will open automatically when it is ready.',
   'waiting'
  );
  return true;
 }catch(_err){
  chatGptAuthWindow=null;
  return false;
 }
}
function maybeOpenChatGptAuthUrl(url){
 const raw=String(url||'').trim();
 if(!raw||raw===chatGptAuthOpenedUrl)return false;
 let parsed;
 try{parsed=new URL(raw)}catch(_err){return false}
 if(!['https:','http:'].includes(parsed.protocol))return false;
 if(parsed.protocol==='http:'&&!['127.0.0.1','localhost','::1'].includes(parsed.hostname))return false;
 chatGptAuthOpenedUrl=raw;
 try{
  if(chatGptAuthWindow&&!chatGptAuthWindow.closed){
   try{chatGptAuthWindow.opener=null}catch(_err){}
   chatGptAuthWindow.location.href=raw;
   return true;
  }
 }catch(_err){}
 return false;
}
function reopenChatGptAuthUrl(){
 const raw=String(chatGptAuthOpenedUrl||'').trim();
 if(!raw)return false;
 window.open(raw,'admira_chatgpt_login');
 return true;
}
function scheduleChatGptConnectPoll(result){
 const r=result?.result||result||{};
 const status=String(r.status||'');
 const shouldPoll=Boolean(r.running)||['browser_login_started','browser_login_waiting','needs_login'].includes(status);
 if(chatGptConnectPollTimer)clearTimeout(chatGptConnectPollTimer);
 if(!shouldPoll)return;
 chatGptConnectPollTimer=setTimeout(()=>pollChatGptConnection(chatGptConnectPurpose,chatGptConnectTarget),2400);
}
function agentModelFormPayload(){
 const form=qs('#agent-model-form');
 return form?Object.fromEntries(new FormData(form).entries()):{};
}
function imageChatGptPayload(){
 const payload=agentModelFormPayload();
 payload.connection_purpose='image';
 payload.codex_image_source='dedicated_chatgpt';
 payload.codex_image_hermes_model='gpt-5.5';
 return payload;
}
function advanceOnboardingAfterChatGptConnected(){
 const flow=qs('#onboarding-flow');
 if(!flow?.classList.contains('open'))return;
 const steps=onboardingSteps();
 const idx=steps.findIndex(s=>s.id==='chatgpt');
 if(idx<0||onboardingFlowStep!==idx)return;
 setOnboardingFlowStep(Math.min(steps.length-1,idx+1));
}
async function pollChatGptConnection(purpose='agent',targetId='chatgpt-connect-result'){
 try{
  chatGptConnectPurpose=purpose||'agent';
  chatGptConnectTarget=targetId||'chatgpt-connect-result';
  rememberOnboardingStep('chatgpt');
  const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='chatgpt');if(idx>=0){onboardingFlowTouched=true;onboardingFlowStep=idx}
  const res=await api('/api/agent-model/connect-status',{method:'POST',body:JSON.stringify({connection_purpose:chatGptConnectPurpose})});
  renderChatGptConnectResult(res,chatGptConnectTarget);
  if((res.result?.status||res.status)==='completed'){await load();await refreshAgentRuntimeStatus(true);if(chatGptConnectPurpose!=='image')advanceOnboardingAfterChatGptConnected()}
 }catch(_err){
  if(chatGptConnectPollTimer)clearTimeout(chatGptConnectPollTimer);
  updateChatGptAuthWindow(
   lang==='es'?'No pude revisar el login':'Could not check login',
   lang==='es'?'Vuelve al dashboard, revisa si la sesión sigue desbloqueada y toca Conectar otra vez.':'Return to the dashboard, check that it is still unlocked, and click Connect again.',
   'error'
  );
 }
}
async function sendChatGptTerminalInput(event){
 event.preventDefault();
 const form=event.target;
 const input=(new FormData(form).get('input')||'').toString();
 if(!input.trim())return;
 const btn=form.querySelector('button');if(btn)btn.disabled=true;
 try{
  const res=await api('/api/agent-model/connect-input',{method:'POST',body:JSON.stringify({input,connection_purpose:chatGptConnectPurpose})});
  form.reset();
  renderChatGptConnectResult(res,chatGptConnectTarget);
 }finally{
  if(btn)btn.disabled=false;
 }
}
function chatGptDeviceAuthHelpMarkup(){
 return `<div id="chatgpt-device-auth-help" class="guide-card chatgpt-settings-help hidden"><b>${lang==='es'?'Si ChatGPT te mostró un error en rojo':'If ChatGPT showed a red error'}</b><p>${lang==='es'?'No pasa nada. Falta activar un permiso de seguridad de ChatGPT para usar Codex con códigos.':'No problem. A ChatGPT security permission must be enabled before Codex can use device codes.'}</p><ol><li>${lang==='es'?'Abre chatgpt.com con la misma cuenta.':'Open chatgpt.com with the same account.'}</li><li>${lang==='es'?'Entra a Configuración.':'Open Settings.'}</li><li>${lang==='es'?'Entra a Seguridad.':'Open Security.'}</li><li>${lang==='es'?'Activa la última opción: “Activar autorización con códigos de dispositivo para Codex”.':'Turn on the last option: “Enable device code authorization for Codex”.'}</li><li>${lang==='es'?'Cierra la pestaña de login de ChatGPT/Codex donde viste el error.':'Close the ChatGPT/Codex login tab where you saw the error.'}</li><li>${lang==='es'?'Vuelve aquí y abre el login otra vez.':'Come back here and open the login again.'}</li></ol><div class="chatgpt-settings-actions"><a class="btn" href="https://chatgpt.com/#settings/Security" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir configuración de ChatGPT':'Open ChatGPT settings'}</a><button class="btn primary chatgpt-retry-login" type="button" data-action-code="reopenChatGptAuthUrl()">${lang==='es'?'Ya lo activé, abrir login de nuevo':'I enabled it, open login again'}</button></div></div>`;
}
function toggleChatGptDeviceAuthHelp(){
 const box=qs('#chatgpt-device-auth-help');
 if(!box)return;
 box.classList.toggle('hidden');
 box.scrollIntoView({behavior:'smooth',block:'center'});
}
function renderChatGptConnectResult(response,targetId='chatgpt-connect-result'){
 const box=qs(`#${targetId||'chatgpt-connect-result'}`);if(!box)return;
 const r=response.result||response||{};
 const status=String(r.status||'');
 const urls=Array.isArray(r.urls)?r.urls:[];
 if(urls.length)maybeOpenChatGptAuthUrl(urls[0]);
 const output=String(r.output||'').trim();
 const running=Boolean(r.running);
 if(!urls.length&&chatGptAuthWindow&&!chatGptAuthOpenedUrl){
  const fatal=['needs_terminal','not_installed'].includes(status)||(!running&&status&&!['terminal_opened','completed','browser_login_started','browser_login_waiting','needs_login'].includes(status));
  updateChatGptAuthWindow(
   r.title||(fatal?(lang==='es'?'No pude abrir el login':'Could not open login'):(lang==='es'?'Preparando login':'Preparing login')),
   r.detail||(fatal?(lang==='es'?'Vuelve al dashboard para ver el diagnóstico y reintentar.':'Return to the dashboard to see the diagnostic and retry.'):(lang==='es'?'Sigo esperando el enlace seguro de ChatGPT/Codex.':'Still waiting for the secure ChatGPT/Codex link.')),
   fatal?'error':'waiting'
  );
 }
 const titles={
  terminal_opened:lang==='es'?'Terminal abierta':'Terminal opened',
  completed:lang==='es'?'Conexión revisada':'Connection checked',
  browser_login_started:lang==='es'?'Login abierto en el servidor':'Server login started',
  browser_login_waiting:lang==='es'?'El agente está esperando':'Agent is waiting',
  needs_login:lang==='es'?'Termina el login':'Finish login',
  needs_terminal:lang==='es'?'Necesita una terminal':'Terminal needed',
 not_installed:lang==='es'?'Falta la base del agente':'Agent base is missing'
 };
 const fallbackTitle=lang==='es'?'No pude conectar automáticamente':'Could not connect automatically';
 const title=escapeHtml(r.title||titles[status]||fallbackTitle);
 const detail=escapeHtml(r.detail||'');
 const autoNote=String(r.auto_note||'').trim();
 const phaseNote=autoNote?`<div class="notice">${escapeHtml(autoNote)}</div>`:'';
 const deviceAuthHelp=r.phase==='device_auth_settings'?`<div class="guide-card chatgpt-settings-help"><b>${lang==='es'?'Haz esto en ChatGPT':'Do this in ChatGPT'}</b><ol><li>${lang==='es'?'Abre ChatGPT con la misma cuenta que usarás aquí.':'Open ChatGPT with the same account you will use here.'}</li><li>${lang==='es'?'Ve a Ajustes > Seguridad.':'Go to Settings > Security.'}</li><li>${lang==='es'?'Activa “Activar autorización con códigos de dispositivo para Codex”.':'Turn on “Enable device code authorization for Codex”.'}</li><li>${lang==='es'?'Cierra la pestaña de login de ChatGPT/Codex donde viste el error.':'Close the ChatGPT/Codex login tab where you saw the error.'}</li><li>${lang==='es'?'Vuelve aquí y abre el login otra vez.':'Come back here and open the login again.'}</li></ol><div class="chatgpt-settings-actions"><a class="btn" href="https://chatgpt.com/#settings/Security" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir configuración de ChatGPT':'Open ChatGPT settings'}</a><button class="btn primary chatgpt-retry-login" type="button" data-action-code="reopenChatGptAuthUrl()">${lang==='es'?'Ya lo activé, abrir login de nuevo':'I enabled it, open login again'}</button></div></div>`:'';
 const loginCode=String(r.login_code||(Array.isArray(r.login_codes)&&r.login_codes.length?r.login_codes[0]:'')||'').trim();
 const codeBlock=loginCode?`<div class="chatgpt-device-code" role="status" aria-live="polite"><div><span>${lang==='es'?'Código para OpenAI':'Code for OpenAI'}</span><strong data-chatgpt-visible-code tabindex="0" aria-label="${lang==='es'?'Código visible para OpenAI':'Visible OpenAI code'}">${escapeHtml(loginCode)}</strong><small>${lang==='es'?'Cópialo manualmente exactamente como aparece y pégalo en la pestaña de OpenAI/Codex que se abrió. Si ChatGPT muestra un error en rojo, toca el botón de ayuda.':'Manually copy it exactly as shown and paste it in the OpenAI/Codex tab that opened. If ChatGPT shows a red error, click the help button.'}</small></div><div class="chatgpt-device-actions"><button class="btn" type="button" data-action-code="toggleChatGptDeviceAuthHelp()">${lang==='es'?'Haz clic aquí si te apareció un error':'Click here if you saw an error'}</button></div></div>${chatGptDeviceAuthHelpMarkup()}`:'';
 const links=urls.length?`<div class="onboarding-step-actions">${urls.map(url=>`<a class="btn primary" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir login':'Open login'}</a>`).join('')}</div>`:'';
 const inputBox=running&&r.needs_input?`<form class="onboarding-mini chatgpt-inline-input" data-submit-code="sendChatGptTerminalInput(event)"><label>${lang==='es'?'Responder al agente':'Reply to agent'}<input name="input" autocomplete="off" placeholder="${lang==='es'?'Ej: número de OpenAI Codex o Enter':'Ex: OpenAI Codex number or Enter'}"></label><button class="btn primary" type="submit">${lang==='es'?'Enviar':'Send'}</button></form>`:'';
 const command='';
 const outputBlock=output?`<details class="helper-command"><summary>${lang==='es'?'Ver diagnóstico técnico':'Show technical diagnostic'}</summary><pre class="chatgpt-terminal-output">${escapeHtml(output)}</pre></details>`:'';
 const review=status==='terminal_opened'||status==='completed'||status==='needs_login'||status==='browser_login_started'||status==='browser_login_waiting'?`<button class="btn primary chatgpt-recheck-main" type="button" data-action-code="pollChatGptConnection()">${lang==='es'?'Ya lo hice, revisar conexión':'I did it, recheck connection'}</button>`:'';
 box.classList.toggle('has-device-code',Boolean(loginCode));
 box.innerHTML=`<b>${title}</b><p>${detail}</p>${phaseNote}${deviceAuthHelp}${codeBlock}${links}${outputBlock}${inputBox}${command}${review?`<div class="onboarding-step-actions">${review}</div>`:''}`;
 box.classList.remove('hidden');
 if(loginCode)setTimeout(()=>box.querySelector('.chatgpt-device-code')?.scrollIntoView({behavior:'smooth',block:'center'}),80);
 scheduleChatGptConnectPoll(r);
}
async function saveChatGptModel(event){
 const btn=event?.currentTarget||event?.target;
 const box=qs('#chatgpt-connect-result');
 if(btn)btn.disabled=true;
 try{
  const payload=agentModelFormPayload();payload.agent_chat_provider='openai_codex';payload.agent_model_action='set_primary';if(!String(payload.hermes_model||'').trim())payload.hermes_model='gpt-5.6-luna';
  await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'Modelo guardado':'Model saved'}</b><p>${lang==='es'?'La conexión de ChatGPT/Codex sigue lista. No abrí otro login.':'ChatGPT/Codex remains connected. I did not open another login.'}</p>`}
  toast(lang==='es'?'Modelo guardado.':'Model saved.');
  await load();
 }catch(err){
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'No pude guardar el modelo':'Could not save model'}</b><p>${escapeHtml(err.message||String(err))}</p>`}
 }finally{
  if(btn)btn.disabled=false;
 }
}
async function refreshCodexModelCatalog(event){
 const btn=event?.currentTarget||event?.target;if(btn)btn.disabled=true;
 try{
  const res=await api('/api/agent-model/catalog',{method:'POST',body:'{}'});
  const catalog=res.result||res||{};
  const count=Array.isArray(catalog.models)?catalog.models.length:0;
  const verified=Boolean(catalog.account_verified);
  toast(lang==='es'
   ? (verified?`Lista verificada con esta cuenta: ${count} modelos`:`Lista provisional actualizada: ${count} modelos; revisa la cuenta conectada`)
   : (verified?`List verified with this account: ${count} models`:`Provisional list refreshed: ${count} models; check the connected account`));
  await load();
 }catch(err){toast(lang==='es'?'No pude renovar la lista; mantuve la última lista válida.':'Could not refresh the list; kept the last known valid list.')}finally{if(btn)btn.disabled=false}
}
async function refreshNvidiaModelCatalog(event){
 const btn=event?.currentTarget||event?.target;
 const form=qs('#agent-model-form');
 if(btn)btn.disabled=true;
 try{
  const payload=agentModelFormPayload();
  const res=await api('/api/agent-model/nvidia-catalog',{method:'POST',body:JSON.stringify({agent_chat_api_key:payload.agent_chat_api_key||''})});
  const catalog=res.result||res||{};
  const models=Array.isArray(catalog.models)?catalog.models:[];
  const count=models.length;
  const datalist=qs('#nvidia-model-options');
  if(datalist)datalist.innerHTML=models.map(value=>`<option value="${escapeHtml(value)}">${escapeHtml(value===catalog.recommended?(lang==='es'?'Recomendado':'Recommended'):'')}</option>`).join('');
  const modelInput=form?.elements?.agent_chat_model;
  if(modelInput){modelInput.setAttribute('list','nvidia-model-options');if(!models.includes(modelInput.value))modelInput.value=catalog.recommended||models[0]||'z-ai/glm-5.2'}
  toast(lang==='es'?`NVIDIA confirmó ${count} modelos de conversación disponibles.`:`NVIDIA confirmed ${count} available chat models.`);
 }catch(err){
  toast(err.message||String(err));
 }finally{if(btn)btn.disabled=false}
}
async function connectChatGpt(event){
 const btn=event?.currentTarget||event?.target;
 const box=qs('#chatgpt-connect-result');
 if(btn)btn.disabled=true;
 chatGptConnectPurpose='agent';
 chatGptConnectTarget='chatgpt-connect-result';
 rememberOnboardingStep('chatgpt');
 const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='chatgpt');if(idx>=0){onboardingFlowTouched=true;onboardingFlowStep=idx}
 const popupReady=prepareChatGptAuthWindow();
 if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'Conectando...':'Connecting...'}</b><p>${popupReady?(lang==='es'?'Abrí una pestaña de espera. Cuando aparezca el login seguro, la llevaré ahí automáticamente.':'I opened a waiting tab. When the secure login appears, I will send it there automatically.'):(lang==='es'?'Si el navegador bloqueó la pestaña, te mostraré un botón para abrir el login.':'If the browser blocked the tab, I will show a button to open the login.')}</p>`}
 try{
  const payload=agentModelFormPayload();if(!String(payload.hermes_model||'').trim())payload.hermes_model='gpt-5.6-luna';
  const res=await api('/api/agent-model/connect',{method:'POST',body:JSON.stringify(payload)});
  renderChatGptConnectResult(res,'chatgpt-connect-result');
  const status=res.result?.status||res.status;
  const urls=res.result?.urls||res.urls||[];
  if((status==='completed'||status==='terminal_opened'||status==='needs_terminal'||status==='not_installed')&&!urls.length&&chatGptAuthWindow&&!chatGptAuthOpenedUrl){
   try{chatGptAuthWindow.close()}catch(_err){}
   chatGptAuthWindow=null;
  }
  if(status==='terminal_opened')toast(lang==='es'?'Abrí la terminal para conectar ChatGPT/Codex.':'Opened the terminal to connect ChatGPT/Codex.');
  else if(status==='completed'){toast(lang==='es'?'Agente conectado correctamente.':'Agent connected successfully.');await load();await refreshAgentRuntimeStatus(true);advanceOnboardingAfterChatGptConnected()}
  else if(String(status).startsWith('browser_login'))toast(lang==='es'?'Login del agente abierto aquí.':'Agent login opened here.');
 }catch(err){
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'No pude abrirlo todavía':'Could not open it yet'}</b><p>${escapeHtml(err.message||String(err))}</p>`}
  updateChatGptAuthWindow(
   lang==='es'?'No pude abrir el login':'Could not open login',
   err.message||String(err)||(
    lang==='es'?'Vuelve al dashboard, desbloquéalo si hace falta y toca Conectar otra vez.':'Return to the dashboard, unlock it if needed, and click Connect again.'
   ),
   'error'
  );
 }finally{
  if(btn)btn.disabled=false;
 }
}
async function connectImageChatGpt(event){
 const btn=event?.currentTarget||event?.target;
 const box=qs('#image-chatgpt-connect-result');
 const form=qs('#agent-model-form');
 if(form?.elements?.codex_image_source)form.elements.codex_image_source.value='dedicated_chatgpt';
 if(btn)btn.disabled=true;
 chatGptConnectPurpose='image';
 chatGptConnectTarget='image-chatgpt-connect-result';
 const popupReady=prepareChatGptAuthWindow();
 if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'Conectando Image 2...':'Connecting Image 2...'}</b><p>${popupReady?(lang==='es'?'Abrí una pestaña de espera para la sesión ChatGPT/Codex de imágenes.':'I opened a waiting tab for the ChatGPT/Codex image session.'):(lang==='es'?'Si el navegador bloqueó la pestaña, te mostraré el enlace aquí.':'If the browser blocked the tab, I will show the link here.')}</p>`}
 try{
  const res=await api('/api/agent-model/connect',{method:'POST',body:JSON.stringify(imageChatGptPayload())});
  renderChatGptConnectResult(res,'image-chatgpt-connect-result');
  const status=res.result?.status||res.status;
  const urls=res.result?.urls||res.urls||[];
  if((status==='completed'||status==='terminal_opened'||status==='needs_terminal'||status==='not_installed')&&!urls.length&&chatGptAuthWindow&&!chatGptAuthOpenedUrl){
   try{chatGptAuthWindow.close()}catch(_err){}
   chatGptAuthWindow=null;
  }
  if(status==='completed'){toast(lang==='es'?'Image 2 conectado.':'Image 2 connected.');await load();await refreshAgentRuntimeStatus(true)}
  else if(String(status).startsWith('browser_login'))toast(lang==='es'?'Login de imágenes abierto aquí.':'Image login opened here.');
 }catch(err){
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'No pude abrirlo todavía':'Could not open it yet'}</b><p>${escapeHtml(err.message||String(err))}</p>`}
  updateChatGptAuthWindow(lang==='es'?'No pude abrir el login':'Could not open login',err.message||String(err),'error');
 }finally{
  if(btn)btn.disabled=false;
 }
}
async function disconnectAgentModel(purpose='agent'){
 const target=purpose==='image'?'image':'agent';
 const box=qs(target==='image'?'#image-chatgpt-connect-result':'#chatgpt-connect-result');
 if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'Desconectando...':'Disconnecting...'}</b><p>${lang==='es'?'Estoy quitando solo la sesión de ChatGPT/Codex guardada en esta instalación.':'Removing only the ChatGPT/Codex session saved in this install.'}</p>`}
 try{
  const res=await api('/api/agent-model/disconnect',{method:'POST',body:JSON.stringify({connection_purpose:target})});
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${escapeHtml(res.title||(lang==='es'?'Desconectado':'Disconnected'))}</b><p>${escapeHtml(res.detail||'')}</p>`}
  toast(target==='image'?(lang==='es'?'Cuenta de imágenes desconectada.':'Image account disconnected.'):(lang==='es'?'ChatGPT/Codex desconectado.':'ChatGPT/Codex disconnected.'));
  await load();
  await refreshAgentRuntimeStatus(true);
 }catch(err){
  if(box){box.classList.remove('hidden');box.innerHTML=`<b>${lang==='es'?'No pude desconectar':'Could not disconnect'}</b><p>${escapeHtml(err.message||String(err))}</p>`}
 }
}
async function saveImageChatGptRouting(source='main_chatgpt'){
 const form=qs('#agent-model-form');
 if(form?.elements?.codex_image_source)form.elements.codex_image_source.value=source;
 const payload=agentModelFormPayload();
 payload.codex_image_source=source;
 await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});
 toast(source==='dedicated_chatgpt'?(lang==='es'?'Image 2 usará ChatGPT separado.':'Image 2 will use separate ChatGPT.'):(lang==='es'?'Image 2 usará la sesión principal.':'Image 2 will use the main session.'));
 await load();
}
function applyAgentModelPreset(kind){
 const form=qs('#agent-model-form');if(!form)return;
 const fields=form.elements;
 const route=kind==='hermes'?'chatgpt_subscription':(kind==='custom'?'custom_api':kind);
 const providerForRoute={openai_api:'openai_api',minimax_m3:'minimax',nvidia_nim:'nvidia_nim',custom_api:'custom_api'};
 const provider=providerForRoute[route]||'openai_codex';
 const connection=(state.config?.agent_model?.connections||{})[provider]||{};
 const defaults={
  openai_api:{base_url:'https://api.openai.com/v1',model:'gpt-4.1-mini'},
  minimax_m3:{base_url:'https://api.minimax.io/v1',model:'MiniMax-M3'},
  nvidia_nim:{base_url:'https://integrate.api.nvidia.com/v1',model:'z-ai/glm-5.2'},
  custom_api:{base_url:'',model:''}
 };
 if(fields.agent_chat_api)fields.agent_chat_api.value='openai-chat-completions';
 if(route==='chatgpt_subscription'){fields.agent_chat_provider.value='openai_codex';if(fields.hermes_model)fields.hermes_model.value='gpt-5.6-luna';return}
 fields.agent_chat_provider.value=provider;
 fields.agent_chat_base_url.value=connection.base_url||defaults[route]?.base_url||'';
 fields.agent_chat_model.value=connection.model||defaults[route]?.model||'';
 if(fields.agent_chat_api)fields.agent_chat_api.value=connection.api||'openai-chat-completions';
 if(fields.agent_chat_api_key){
  fields.agent_chat_api_key.value='';
  fields.agent_chat_api_key.placeholder=connection.api_key_set?(lang==='es'?'Clave guardada. Pega otra solo si quieres cambiarla.':'Key saved. Paste another only to replace it.'):(lang==='es'?'Pega la clave API del proveedor':'Paste the provider API key');
 }
}
function selectAgentModelRoute(kind){
 const route=kind==='hermes'?'chatgpt_subscription':(kind==='custom'?'custom_api':kind);
 applyAgentModelPreset(route);
 const form=qs('#agent-model-form');
 const modelInput=form?.elements?.agent_chat_model;
 const baseInput=form?.elements?.agent_chat_base_url;
 if(modelInput){if(route==='nvidia_nim')modelInput.setAttribute('list','nvidia-model-options');else modelInput.removeAttribute('list')}
 if(baseInput)baseInput.readOnly=route==='nvidia_nim';
 document.querySelectorAll('[data-agent-route]').forEach(btn=>{
  const active=btn.dataset.agentRoute===route;
  btn.classList.toggle('active',active);
  btn.setAttribute('aria-expanded',active?'true':'false');
 });
 document.querySelectorAll('[data-agent-route-panel]').forEach(panel=>{
  const panelRoute=panel.dataset.agentRoutePanel;
  panel.classList.toggle('active',panelRoute===route||(panelRoute==='api'&&route!=='chatgpt_subscription'));
 });
 const copy={
  openai_api:{title:lang==='es'?'OpenAI API':'OpenAI API',help:lang==='es'?'Pega tu clave API de OpenAI. El agente la usará como cerebro sin perder memoria, herramientas ni aprobaciones.':'Paste your OpenAI API key. The agent will use it as its brain while keeping memory, tools, and approvals.'},
  minimax_m3:{title:'MiniMax M3',help:lang==='es'?'Pega tu clave de MiniMax. Ya dejé URL y modelo listos para M3. El agente seguirá usando su memoria y herramientas.':'Paste your MiniMax key. URL and model are already set for M3. The agent still keeps memory and tools.'},
  nvidia_nim:{title:'NVIDIA NIM',help:lang==='es'?'Pega tu API key de NVIDIA y carga los modelos disponibles ahora. El endpoint alojado puede aplicar cuotas o límites temporales.':'Paste your NVIDIA API key and load the models currently available. The hosted endpoint may apply quotas or temporary limits.'},
  custom_api:{title:lang==='es'?'Otra API compatible':'Other compatible API',help:lang==='es'?'Pega la URL, el nombre del modelo y la clave del proveedor. El agente la usará como cerebro.':'Paste the provider URL, model name, and key. The agent will use it as its brain.'}
 };
 if(copy[route]){
  const title=qs('#agent-api-route-title');const help=qs('#agent-api-route-help');
  if(title)title.textContent=copy[route].title;
  if(help)help.textContent=copy[route].help;
  const primary=state.config?.agent_model?.brain_provider||'openai_codex';
  const providerForRoute={openai_api:'openai_api',minimax_m3:'minimax',nvidia_nim:'nvidia_nim',custom_api:'custom_api'};
  const isPrimary=providerForRoute[route]===primary;
  const primaryButton=qs('#set-agent-primary');
  if(primaryButton)primaryButton.textContent=isPrimary?(lang==='es'?'Ya es principal':'Already primary'):(lang==='es'?'Usar como principal':'Use as primary');
 }
}
function renderTelegramPanel(){
 const v=state.config.telegram_agent||{};
 const ready=v.enabled&&v.bot_configured&&v.chat_id;
 const checked=v.enabled?'checked':'';
 qs('#telegram-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Hablar por Telegram':'Talk through Telegram'}</b><p>${lang==='es'?'Conecta un bot privado para conversar con el manager desde tu celular y aprobar decisiones exactas con botones seguros.':'Connect a private bot to talk with the manager from your phone and approve exact decisions with safe buttons.'}</p></div><span class="badge ${ready?'ok':'warn'}">${ready?(lang==='es'?'Listo':'Ready'):(lang==='es'?'Pendiente':'Pending')}</span></div><div class="setup-guide private-connection telegram-onboarding"><section class="guide-hero"><div class="guide-main"><span class="guide-eyebrow">Telegram</span><h3>${lang==='es'?'Crea tu bot privado':'Create your private bot'}</h3><p>${lang==='es'?'Usa BotFather una sola vez. Pega la clave aquí y la guardaré automáticamente.':'Use BotFather once. Paste the key here and I will save it automatically.'}</p><div class="guide-actions"><a class="btn primary" href="https://telegram.org/dl" target="_blank" rel="noopener noreferrer">${lang==='es'?'Descargar Telegram':'Download Telegram'}</a><a class="btn" href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">${lang==='es'?'Abrir BotFather':'Open BotFather'}</a><button class="btn" type="button" data-action-code="copyCommand('/newbot')">${lang==='es'?'Copiar /newbot':'Copy /newbot'}</button></div></div><aside class="guide-checklist"><b>${lang==='es'?'Pasos simples':'Simple steps'}</b><ol><li>${lang==='es'?'Busca BotFather y escribe /newbot.':'Search BotFather and send /newbot.'}</li><li>${lang==='es'?'Ponle nombre y usuario terminado en bot.':'Give it a name and username ending in bot.'}</li><li>${lang==='es'?'Pega aquí la clave larga.':'Paste the long key here.'}</li><li>${lang==='es'?'Envíale hola a tu bot y detecta el chat.':'Send hello to your bot and detect the chat.'}</li></ol></aside></section>${telegramVideoMarkup()}</div><form id="telegram-config-form" class="form-grid telegram-token-form">
 <div class="field wide telegram-token-zone ${v.bot_configured?'saved':''}"><label>${lang==='es'?'Clave larga que te dio BotFather':'Long key from BotFather'}</label><span class="field-help" data-telegram-token-help>${v.bot_configured?(lang==='es'?'Clave guardada. Pega otra solo si quieres cambiarla.':'Key saved. Paste another only to replace it.'):(lang==='es'?'Pégala completa. La guardaré automáticamente en este PC/VPS.':'Paste it complete. I will save it automatically on this PC/VPS.')}</span>${v.bot_configured?telegramTokenSavedInline():''}<input type="password" name="bot_token" value="" data-input-code="autoSaveTelegramToken(event)" data-paste-code="autoSaveTelegramToken(event)" autocomplete="off" placeholder="${v.bot_configured?(lang==='es'?'Clave guardada':'Key saved'):'123456:ABC...'}"></div>
 <div class="field"><label>${lang==='es'?'Tu chat privado':'Your private chat'}</label><span class="field-help">${lang==='es'?'Se llena cuando detecto tu "hola".':'Filled when I detect your "hello".'}</span><input name="chat_id" value="${escapeHtml(v.chat_id||'')}" placeholder="${lang==='es'?'Pendiente':'Pending'}" data-change-code="autoSaveTelegramSetting(event)"></div>
 <div class="field"><label>${lang==='es'?'Idioma del manager':'Manager language'}</label><select name="language" data-change-code="autoSaveTelegramSetting(event)"><option value="es" ${v.language!=='en'?'selected':''}>Español</option><option value="en" ${v.language==='en'?'selected':''}>English</option></select></div>
 <label class="field wide"><input type="checkbox" name="enabled" ${checked} data-change-code="autoSaveTelegramSetting(event)"> ${lang==='es'?'Activar conversación por Telegram':'Enable Telegram conversation'}</label>
 </form><div id="telegram-results">${telegramStatusMarkup(v)}</div><p class="notice">${lang==='es'?'No puedo crear el bot por ti porque Telegram entrega la clave dentro de BotFather. Sí puedo guardar la clave, detectar tu chat y dejar el manager listo para responder desde Telegram.':'I cannot create the bot for you because Telegram gives the key inside BotFather. I can save the key, detect your chat, and keep the manager ready to reply through Telegram.'}</p>`;
}
function renderCommunicationStylePanel(){
 const box=qs('#communication-style-panel');if(!box)return;
 box.innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Forma de hablar del agente':'Agent communication style'}</b><p>${lang==='es'?'Cámbiala cuando quieras. Es una preferencia global y se usa igual para todos tus negocios o clientes.':'Change it anytime. This global preference is used for every business or client.'}</p></div></div>${communicationStyleGuide(false)}`;
}
function renderMigrationPanel(){
 qs('#migration-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Cambiar de equipo sin perder memoria':'Move device without losing memory'}</b><p>${lang==='es'?'Crea una copia segura de esta instalación o trae una copia anterior. Incluye chat, marca, productos, configuración y memoria del dashboard.':'Create a safe copy of this install or bring back an earlier one. It includes chat, brand, products, setup, and dashboard memory.'}</p></div><div class="mode-actions"><button class="btn primary" type="button" data-action-code="downloadMigrationBackup()">${lang==='es'?'Crear copia segura':'Create safe copy'}</button><button class="btn" type="button" data-action-code="qs('#migration-restore-file').click()">${lang==='es'?'Traer copia anterior':'Restore backup'}</button><input id="migration-restore-file" class="hidden" type="file" accept=".tar.gz,.tgz,.zip,application/gzip,application/zip" data-change-code="restoreMigrationBackup(event)"></div></div><div id="migration-result"></div><p class="notice">${lang==='es'?'Esa copia puede incluir claves privadas. Guárdala como guardarías una llave de tu negocio.':'The backup may contain private keys. Store it like a key to your business.'}</p>`;
}
function renderLocalNetworkPanel(){
 const box=qs('#local-network-panel');if(!box)return;
 const net=state.local_network_access||{};
 if(net.install_environment==='cloud'){box.innerHTML='';return}
 const enabled=Boolean(net.enabled);
 const active=Boolean(net.active);
 const url=net.lan_url||'';
 const status=enabled?(active?(lang==='es'?'Activo':'Active'):(lang==='es'?'Reiniciando':'Restarting')):(lang==='es'?'Apagado':'Off');
 const body=lang==='es'
  ? 'Actívalo solo cuando quieras abrir este dashboard desde tu teléfono. El teléfono debe estar conectado al mismo Wi‑Fi o red local, y seguirá pidiendo tu contraseña.'
  : 'Turn this on only when you want to open this dashboard from your phone. The phone must be on the same Wi‑Fi or local network, and your password is still required.';
 const linkBlock=enabled?`<div class="guide-card"><b>${lang==='es'?'Enlace para tu teléfono':'Phone link'}</b><p>${url?escapeHtml(url):(lang==='es'?'No pude detectar el IP automáticamente. Usa el IP local de este computador con el puerto '+escapeHtml(String(net.port||7871))+'.':'I could not detect the IP automatically. Use this computer local IP with port '+escapeHtml(String(net.port||7871))+'.')}</p><div class="onboarding-step-actions">${url?`<button class="btn primary" type="button" data-action-code="copyCommand(${JSON.stringify(url).replaceAll('"','&quot;')})">${lang==='es'?'Copiar enlace':'Copy link'}</button>`:''}<button class="btn ask-btn" type="button" data-action-code="openChat(${chatArg(lang==='es'?'Quiero abrir el dashboard desde mi teléfono. Explícame los pasos simples y qué revisar si no carga.':'I want to open the dashboard from my phone. Explain the simple steps and what to check if it does not load.')})">${t('ask_agent')}</button></div></div>`:'';
 const restartNote=net.restart_needed?`<p class="notice">${lang==='es'?'Estoy aplicando el cambio. Si la página se desconecta unos segundos, vuelve a abrir el enlace cuando termine.':'Applying the change. If the page disconnects for a few seconds, reopen the link when it finishes.'}</p>`:'';
 box.innerHTML=`<section class="chatgpt-connect-card local-network-card ${enabled?'ready':''}"><div class="chatgpt-connect-head"><div><h3>${lang==='es'?'Ver desde mi teléfono':'View from my phone'}</h3><p>${body}</p></div><span class="badge ${enabled?'ok':'warn'}">${status}</span></div><div class="model-route-grid"><div class="model-route-card"><span>1</span><b>${lang==='es'?'Mismo Wi‑Fi':'Same Wi‑Fi'}</b><p>${lang==='es'?'Tu teléfono y este computador deben estar en la misma red.':'Your phone and this computer must be on the same network.'}</p></div><div class="model-route-card"><span>2</span><b>${lang==='es'?'Con contraseña':'Password protected'}</b><p>${lang==='es'?'Aunque alguien vea el enlace, necesita la contraseña del dashboard para acciones y datos protegidos.':'Even if someone sees the link, the dashboard password is required for protected data and actions.'}</p></div></div>${linkBlock}${restartNote}<div class="mode-actions"><button class="btn ${enabled?'':'primary'}" type="button" data-action-code="setLocalNetworkAccess(true)">${lang==='es'?'Activar para teléfono':'Turn on phone access'}</button><button class="btn ${enabled?'primary':''}" type="button" data-action-code="setLocalNetworkAccess(false)">${lang==='es'?'Apagar acceso por Wi‑Fi':'Turn off Wi‑Fi access'}</button></div></section>`;
}
function renderCloudAccessPanel(){
 qs('#cloud-access-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Mantener acceso cuando estás en la nube':'Keep cloud dashboard access'}</b><p>${lang==='es'?'Si este dashboard ya abrió desde tu red actual, este botón autoriza esta red en DigitalOcean. Úsalo cuando cambies de Wi-Fi antes de cerrar la página.':'If this dashboard already opened from your current network, this button authorizes this network in DigitalOcean. Use it when you change Wi-Fi before closing the page.'}</p></div><div class="mode-actions"><button class="btn" type="button" data-action-code="refreshCloudAccess()">${lang==='es'?'Permitir esta red':'Allow this network'}</button></div></div><div id="cloud-access-result"></div><p class="notice">${lang==='es'?'Si el dashboard no carga porque tu IP ya cambió, este botón no puede ayudarte todavía. Recupera entrada desde el portal de DigitalOcean, SSH o la consola web; después vuelve aquí para dejar la nueva red guardada.':'If the dashboard does not load because your IP already changed, this button cannot help yet. Recover access from the DigitalOcean portal, SSH, or web console; then return here to save the new network.'}</p>`;
}
function renderUpdateRollbackPanel(){
 if(!state?.onboarding?.completed){qs('#update-rollback-panel').innerHTML='';return}
 qs('#update-rollback-panel').innerHTML=`<div class="next-step"><div><b>${lang==='es'?'Actualizaciones y copias':'Updates and backups'}</b><p>${lang==='es'?'El dashboard busca releases nuevas cada minuto mientras está abierto. Las actualizaciones oficiales se instalan automáticamente a las 3:00 a. m. y te aviso a las 9:00 a. m. si hubo una. Antes de cada cambio se guarda una copia segura.':'The dashboard checks for new releases every minute while open. Official updates install automatically at 3:00 AM, with one 9:00 AM notice only when an update was installed. A safe copy is saved before every change.'}</p></div><div class="mode-actions"><button class="btn" type="button" data-action-code="loadUpdateSnapshots(true)">${lang==='es'?'Ver copias guardadas':'View saved copies'}</button></div></div><div id="update-snapshot-list"></div>`;
 loadUpdateSnapshots(false);
}
function updateCardsMarkup(info){
 const cards=(info?.improvements||[]).map(item=>`<div class="update-card"><span>${escapeHtml(item.impact||'Optimización')}</span><b>${escapeHtml(item.title||'Mejora incluida')}</b><p>${escapeHtml(item.body||'Actualización publicada desde el canal oficial.')}</p></div>`).join('');
 return `<div class="update-cards">${cards}</div>`;
}
function updateWarningsMarkup(info){
 const warnings=info?.warnings||[];if(!warnings.length)return '';
 return `<div class="update-cards">${warnings.map(item=>`<div class="update-card"><span>${lang==='es'?'Atención':'Warning'}</span><b>${escapeHtml(localText(item.title||''))}</b><p>${escapeHtml(localText(item.body||''))}</p></div>`).join('')}</div>`;
}
function renderUpdateBanner(info){
 const box=qs('#update-banner');if(!box)return;
 const latest=String(info?.latest_version||'').trim();
 const current=String(info?.current_version||'').trim();
 const acknowledged=localStorage.getItem(UPDATE_INSTALLED_ACK_KEY)||'';
 if(!info?.available||!latest||acknowledged===latest){box.classList.add('hidden');box.innerHTML='';return}
 box.innerHTML=`<div><b>${lang==='es'?'Nueva actualización disponible':'New update available'}</b><p>${escapeHtml(current)} → ${escapeHtml(latest)}</p></div><button class="btn primary" type="button" data-action-code="showUpdateDetails()">${lang==='es'?'Ver actualización':'View update'}</button>`;
 box.classList.remove('hidden');
}
function renderDeferredOnboardingBanner(){
 const box=qs('#deferred-onboarding-banner');if(!box)return;
 const onboarding=state.onboarding||{};
 const deferred=Boolean(onboarding.deferred||onboarding.skipped||onboarding.requires_repair);
 if(!deferred){box.classList.add('hidden');box.innerHTML='';return}
 const agentInterviewReasons=new Set(['entrevista_negocio','branding_creativos','campanas_anuncios','perfil_negocio']);
 const reasons=(onboarding.deferred_reasons||onboarding.repair_reasons||[]).filter(reason=>reason&&!agentInterviewReasons.has(reason));
 if(!reasons.length){box.classList.add('hidden');box.innerHTML='';return}
 const labelMap={
  licencia:lang==='es'?'licencia':'license',
  conexion_facebook:lang==='es'?'Facebook':'Facebook',
  cuenta_publicitaria:lang==='es'?'cuenta publicitaria':'ad account',
  cerebro_agente:lang==='es'?'ChatGPT':'ChatGPT',
  telegram:'Telegram',
  conexion_meta:lang==='es'?'Facebook':'Facebook',
  destinos:lang==='es'?'página y web':'Page and website',
  datos_reales:lang==='es'?'datos reales':'real data',
  perfil_negocio:lang==='es'?'perfil del negocio':'business profile'
 };
 const summary=reasons.length?reasons.slice(0,3).map(reason=>labelMap[reason]||reason).join(', '):(lang==='es'?'algunos pasos':'some steps');
 box.classList.remove('hidden');
 box.innerHTML=`<div class="deferred-onboarding-copy"><span class="pulse-dot"></span><div><b>${lang==='es'?'Completa la configuración para ver datos reales':'Finish setup to see real data'}</b><p>${lang==='es'?`Falta revisar: ${summary}. Mientras falte esto, puedes ver el dashboard con ejemplos, pero el agente no analizará campañas reales.`:`Still to review: ${summary}. Until this is done, the dashboard can show examples, but the agent will not analyze real campaigns.`}</p></div></div><button class="btn primary" type="button" data-action-code="resumeOnboarding()">${lang==='es'?'Completar ahora':'Finish now'}</button>`;
}
function showUpdateDetails(){
 if(!updateInfo)return;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card guide-modal-card"><div class="next-step"><div><h2>${lang==='es'?'Actualización oficial':'Official update'}</h2><p>${lang==='es'?'Versión':'Version'}: ${escapeHtml(updateInfo.current_version||'')} → ${escapeHtml(updateInfo.latest_version||'')}</p></div><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cerrar':'Close'}</button></div>${updateWarningsMarkup(updateInfo)}${updateCardsMarkup(updateInfo)}<p class="notice">${lang==='es'?'Antes de cambiar archivos crearé una copia de seguridad. Si algo falla, podrás volver desde Configuración. Meta seguirá ejecutando lo que ya esté activo fuera del dashboard.':'Before changing files I will create a backup. If something fails, you can return from Setup. Meta will keep running anything already active outside the dashboard.'}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Ahora no':'Not now'}</button><button class="btn primary" type="button" data-action-code="applyDashboardUpdate()">${lang==='es'?'Crear copia e instalar':'Backup and install'}</button></div></div>`;box.classList.add('open');
}
function startUpdateAutoCheck(){
 if(updateAutoTimer)return;
 const poll=()=>{if(document.hidden||!dashboardPassword())return;checkForUpdates(false,{silent:true})};
 poll();
 updateAutoTimer=setInterval(poll,UPDATE_CHECK_POLL_MS);
 window.addEventListener('beforeunload',()=>{if(updateAutoTimer){clearInterval(updateAutoTimer);updateAutoTimer=null}},{once:true});
}
async function checkForUpdates(force=false,options={}){
 const now=Date.now();
 if(updateCheckInFlight)return;
 if(updateCheckStarted&&!force&&updateLastCheckedAt&&now-updateLastCheckedAt<UPDATE_CHECK_COOLDOWN_MS)return;
 if(!dashboardPassword())return;
 updateCheckStarted=true;
 updateCheckInFlight=true;
 updateLastCheckedAt=now;
 const silent=Boolean(options.silent);
 try{const res=await api('/api/update/check',{method:'POST',body:'{}'});updateInfo=res.result||null;updateCheckError='';renderUpdateBanner(updateInfo);if(force&&!silent)toast(updateInfo?.available?(lang==='es'?'Actualización disponible':'Update available'):(lang==='es'?'Ya tienes la versión más reciente':'You already have the latest version'));return updateInfo}catch(err){updateCheckError=String(err?.message||err||'').trim();if(force&&!silent)toast(updateCheckError||(lang==='es'?'No pude revisar actualizaciones':'Could not check for updates'));return null}finally{updateCheckInFlight=false}
}
async function applyDashboardUpdate(){
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Instalando actualización':'Installing update'}</h2><p>${lang==='es'?'Estoy descargando el paquete oficial y conservando tus datos locales. El dashboard se reiniciará al terminar.':'Downloading the official package and keeping local data. The dashboard will restart when finished.'}</p></div>`;box.classList.add('open');
 try{const res=await api('/api/update/apply',{method:'POST',body:'{}'});const installedVersion=String(res.result?.latest_version||updateInfo?.latest_version||'').trim();if(installedVersion){localStorage.setItem(UPDATE_INSTALLED_ACK_KEY,installedVersion);updateInfo={...(res.result||updateInfo||{}),available:false,current_version:installedVersion,latest_version:installedVersion};renderUpdateBanner(updateInfo)}box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Actualización instalada':'Update installed'}</h2><p>${escapeHtml(res.result?.message||'')}</p><p class="notice">${lang==='es'?'Copia guardada':'Saved backup'}: ${escapeHtml(res.result?.snapshot?.id||'')}</p><p class="notice">${lang==='es'?'Si la página tarda unos segundos, espera y recarga.':'If the page takes a few seconds, wait and refresh.'}</p></div>`;toast(lang==='es'?'Actualización instalada':'Update installed')}catch(err){box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'No pude actualizar':'Could not update'}</h2><p>${escapeHtml(err.message||String(err))}</p><p class="notice">${lang==='es'?'Si la copia se creó, estará disponible en Configuración para restaurar.':'If a backup was created, it will be available in Setup to restore.'}</p><div class="confirm-actions"><button class="btn primary" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cerrar':'Close'}</button></div></div>`}
}
function setupSimpleText(item){
 const es={
  license_key:['Licencia','Pega y activa el código que recibiste al comprar.'],
  ad_account:['Cuenta publicitaria','Elige la cuenta de Meta Ads que quieres que el agente cuide.'],
  access_token:['Clave de Meta','Pega la clave de acceso que creaste siguiendo tus imágenes de guía.'],
  page_id:['Página de Facebook','Elige la página desde donde saldrán tus anuncios.'],
  landing_url:['Link de tu web','Guarda la página a la que llegarán las personas.'],
  dashboard_token:['Contraseña del dashboard','Crea una contraseña para proteger acciones importantes.'],
  hermes_runtime:['Chat con agente','Falta conectar la base del agente para usar tu sesión de ChatGPT/Codex.'],
  hermes_auth:['ChatGPT/Codex','Conecta el agente con tu cuenta de ChatGPT/Codex.'],
  openai_compatible_model:['Modelo del agente','Si usas MiniMax M3 u otra API, falta guardar URL, modelo y clave.'],
  connector:['Conexión con Meta','Falta pegar una clave válida de Meta para leer y ejecutar acciones.'],
  daily_report:['Lectura diaria','Todavía no hay resumen diario. Puedes tocar Actualizar o pedírselo al agente.'],
  gemini_key:['Crear imágenes','Opcional: falta conectar la clave para generar imágenes reales.'],
  telegram_bot:['Telegram','Opcional: falta la clave del bot si quieres hablar desde Telegram.'],
  telegram_chat:['Telegram','Opcional: falta elegir tu chat privado.'],
  creative_index:['Ideas de anuncios','Todavía no hay ideas de anuncios creadas.'],
  latest_upload:['Publicar anuncios','Todavía no hay anuncios preparados para revisar.'],
 };
 const en={
  license_key:['License','Paste and activate the code you received after purchase.'],
  ad_account:['Ad account','Choose the Meta Ads account this agent should manage.'],
  access_token:['Meta key','Paste the access key you created with your screenshots.'],
  page_id:['Facebook Page','Choose the Page your ads will publish from.'],
  landing_url:['Website link','Save the page people will visit.'],
  dashboard_token:['Dashboard password','Create a password to protect important actions.'],
  hermes_runtime:['Agent chat','Connect the agent base so chat can use your ChatGPT/Codex session.'],
  hermes_auth:['ChatGPT/Codex','Connect the agent with your ChatGPT/Codex account.'],
  openai_compatible_model:['Agent model','If you use MiniMax M3 or another API, save URL, model, and key.'],
  connector:['Meta connection','Paste a valid Meta key to read data and execute actions.'],
  daily_report:['Daily reading','No daily brief exists yet. Click Refresh or ask the agent.'],
  gemini_key:['Create images','Optional: connect the key for real image generation.'],
  telegram_bot:['Telegram','Optional: add the bot key if you want to chat from Telegram.'],
  telegram_chat:['Telegram','Optional: choose your private chat.'],
  creative_index:['Ad ideas','No ad ideas have been created yet.'],
  latest_upload:['Publish ads','No ads are prepared for review yet.'],
 };
 const dict=lang==='es'?es:en;const found=dict[item.key];
 if(found)return {title:found[0],body:found[1]};
 return {title:localText(item.label),body:localText(item.action||item.detail||'')};
}
function renderSetupBeginnerSummary(setup){
 const all=setup.sections.flatMap(sec=>sec.items||[]);
 const blocked=all.filter(i=>i.status==='blocked');
 const warnings=all.filter(i=>i.status==='warn');
 const list=(blocked.length?blocked:warnings).slice(0,4);
 const good=!blocked.length&&!warnings.length;
 const title=good?(lang==='es'?'Todo lo importante se ve listo':'The important pieces look ready'):(blocked.length?(lang==='es'?'Lo que falta primero':'Fix these first'):(lang==='es'?'Cosas para revisar':'Things to review'));
 const body=good?(lang==='es'?'Tu configuración principal está en verde. Si algo te confunde, pregúntale al agente antes de activar campañas.':'Your main setup is green. If anything feels unclear, ask the agent before activating campaigns.'):(lang==='es'?'No necesitas entender cada detalle técnico. Empieza por estas tarjetas y el agente puede explicarte una por una.':'You do not need to understand every technical detail. Start with these cards and the agent can explain them one by one.');
 return `<div class="guide-panel setup-simple-panel"><div class="next-step"><div><b>${title}</b><p>${body}</p></div><button class="btn ask-btn" type="button" data-action-code="openChat(lang==='es'?'Explícame qué falta en mi configuración con palabras muy simples y dime qué hago primero.':'Explain what is missing in my setup in very simple words and tell me what to do first.')">${t('ask_agent')}</button></div>${list.length?`<div class="trust-grid">${list.map(item=>{const copy=setupSimpleText(item);return `<div class="trust-card"><b>${statusLabel(item.status)} · ${escapeHtml(copy.title)}</b><p>${escapeHtml(copy.body)}</p></div>`}).join('')}</div>`:''}</div>`;
}
function renderSetupTechnicalDetails(setup){
 return `<details class="fallback-details setup-technical-details"><summary>${lang==='es'?'Revisión técnica para soporte':'Technical review for support'}</summary>${setup.sections.map(sec=>`<div class="section"><div class="head"><b>${localText(sec.title)}</b></div><div class="body">${sec.items.map(i=>`<div class="log-item"><b>${statusLabel(i.status)} - ${localText(i.label)}</b><br>${localText(i.detail||'')}${i.action?`<br><span class="notice">${localText(i.action)}</span>`:''}</div>`).join('')}</div></div>`).join('')}</details>`;
}
function renderSetup(){const setup=state.setup;const counts=setup.summary.counts;renderModeControl();renderGuardrails();renderOnboarding();renderLicensePanel();renderMetaConnectionPanel();renderPublishingPanel();renderSetupConfig();renderChatGptPanel();renderTelegramPanel();renderCommunicationStylePanel();renderLocalNetworkPanel();renderMigrationPanel();renderUpdateRollbackPanel();renderCloudAccessPanel();qs('#setup-summary').innerHTML=`<div class="kpis">${kpi(t('ok'),counts.ok||0)}${kpi(t('warnings'),counts.warn||0)}${kpi(t('blocked'),counts.blocked||0)}${kpi(t('live_ready'),setup.summary.live_ads_ready?t('live_ready_yes'):t('live_ready_no'))}</div>`;qs('#setup-sections').innerHTML=renderSetupBeginnerSummary(setup)+renderSetupTechnicalDetails(setup)}
function audienceText(value){
 const raw=String(value||'');if(lang!=='es')return raw;
 const exact={
  'Broad / Advantage+ prospecting':'Llegar a personas nuevas',
  'Prospección amplia / Advantage+':'Llegar a personas nuevas',
  'Interest testing':'Personas con intereses relacionados',
  'Prueba por intereses':'Personas con intereses relacionados',
  'Warm retargeting':'Personas que ya te conocen',
  'Retargeting tibio':'Personas que ya te conocen',
  'Lookalike from seed audience':'Personas parecidas a tus mejores clientes',
  'Lookalike desde audiencia semilla':'Personas parecidas a tus mejores clientes',
  'Use after the seed source is clean and large enough.':'Úsalo cuando ya tengas suficientes visitas o compradores reales.',
  'Úsalo cuando la audiencia semilla esté limpia y tenga suficiente tamaño.':'Úsalo cuando ya tengas suficientes visitas o compradores reales.',
  'Las audiencias tibias suelen convertir mejor, pero se fatigan rápido si son pequeñas.':'Las personas que ya te conocen suelen comprar más fácilmente, pero el mismo anuncio puede cansarlas si son pocas.',
  'Lanza primero amplia + una prueba de intereses.':'Empieza llegando a personas nuevas y prueba un grupo con intereses.',
  'Separa retargeting si ya existe tráfico tibio.':'Si ya tienes visitas o mensajes, prepara un grupo aparte para esas personas.',
  'Crea lookalike solo cuando la data semilla y el consentimiento estén claros.':'Prueba personas parecidas solo cuando tengas suficientes datos y permiso para usarlos.',
 };
 if(exact[raw])return exact[raw];
 if(raw.startsWith('Meta usually finds buyers faster'))return 'Empieza sin poner demasiados filtros. Las imágenes, textos y resultados ayudarán al agente a encontrar compradores.';
 if(raw.startsWith('Start with interests that describe'))return 'Prueba temas que ya le interesan a tu comprador, sin limitar demasiado el alcance.';
 if(raw.startsWith('Lookalikes can scale what already works'))return 'Las personas parecidas pueden ampliar lo que ya funciona, siempre que los datos de partida sean buenos.';
 return raw;
}
function audienceTargetingText(targeting){
 if(lang!=='es')return JSON.stringify(targeting||{});
 const value=targeting||{}, parts=[];
 if(value.locations?.length)parts.push(`Lugar: ${value.locations.join(', ')}`);
 if(value.age)parts.push(`Edad: ${value.age}`);
 if(value.interests?.length)parts.push(`Intereses: ${value.interests.join(', ')}`);
 if(value.sources?.length)parts.push(`Ya te conocen por: ${value.sources.map(source=>source==='Pixel / IG engagement / leads'?'visitas web, Instagram o formularios':source).join(', ')}`);
 if(value.window)parts.push('Probar durante: 7, 14 y 30 días');
 if(value.exclusions)parts.push('Evitar mostrarlo a compradores recientes, si puedes identificarlos');
 if(value.seed)parts.push('Basado en: visitantes, compradores o personas que interactuaron');
 if(value.sizes)parts.push('Probar cercanía: 1%, 2% y 5%');
 return parts.join(' · ')||'El agente ajustará este público con lo que le cuentes.';
}
function renderAudience(){
 const r=state.audience_strategy||{};const box=qs('#audience-result');if(!box)return;
 if(!r.strategies){box.innerHTML=`<p class="notice">${lang==='es'?'Completa estas preguntas para que el agente te sugiera a qué personas mostrar tus anuncios. El agente no sube listas de clientes todavía; solo te dirá si valdría la pena después.':'Fill the form to create a clear targeting recommendation. The agent does not upload customer lists yet; it only checks whether that would make sense later.'}</p>`;return}
 const ready=r.lookalike_readiness?.ready;
 box.innerHTML=`<div class="trust-grid"><div class="trust-card"><b>${t('lookalike_status')}</b><p>${ready?(lang==='es'?'Ya tienes información suficiente para probar con personas parecidas a tus clientes o visitantes.':'You have enough information to test with people similar to your customers or visitors.'):(lang==='es'?'Todavía no conviene. Primero reúne visitas, interacciones o una lista de clientes que te dio permiso.':'Not yet. First gather visits, interactions, or a customer list with permission.')}</p></div><div class="trust-card"><b>${lang==='es'?'Qué falta':'What is missing'}</b><p>${escapeHtml((r.blockers&&r.blockers.length?r.blockers.map(audienceText):[lang==='es'?'Nada importante por resolver.':'Nothing important to resolve.']).join(' '))}</p></div><div class="trust-card"><b>${lang==='es'?'Producto':'Product'}</b><p>${escapeHtml(r.product||'')}</p></div></div><h3 data-style-code="font-size:13px;margin:8px 0">${t('recommended_audiences')}</h3>${r.strategies.map(s=>`<div class="rec-card"><h3>${escapeHtml(audienceText(s.name))}</h3><p class="notice">${escapeHtml(audienceText(s.use_when))}</p><div class="action-detail"><strong>${lang==='es'?'Por qué':'Why'}:</strong> ${escapeHtml(audienceText(s.why))}<br><strong>${lang==='es'?'Personas que verá':'People it reaches'}:</strong> ${escapeHtml(audienceTargetingText(s.targeting))}</div></div>`).join('')}<h3 data-style-code="font-size:13px;margin:8px 0">${t('next_steps')}</h3>${(r.next_steps||[]).map(step=>`<div class="log-item">${escapeHtml(audienceText(step))}</div>`).join('')}`;
}
function spark(vals){const w=220,h=46,max=Math.max(...vals,1),min=Math.min(...vals,0),range=max-min||1;const pts=vals.map((v,i)=>`${i*(w/(vals.length-1))},${h-((v-min)/range*h*.78+5)}`).join(' ');return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="#7c5cff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><line x1="0" y1="${h-4}" x2="${w}" y2="${h-4}" stroke="#2a2a30"/></svg>`}
function campaignButtons(c){
 if(c.status==='paused')return `<button class="btn primary" data-action-code="campaignAction('resume','${c.id}')">${t('resume')}</button><button class="btn" data-action-code="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn" data-action-code="showDetails('${c.id}')">${t('details')}</button>`;
 if(c.health==='winning')return `<button class="btn primary" data-action-code="budgetPrompt('${c.id}',${Math.round(Number(c.daily_budget||0)*1.15)})">${t('increase_budget')}</button><button class="btn" data-action-code="showDetails('${c.id}')">${t('details')}</button><button class="btn" data-action-code="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button>`;
 if(c.health==='fatigue')return `<button class="btn primary" data-action-code="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn" data-action-code="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn danger" data-action-code="campaignAction('pause','${c.id}')">${t('pause')}</button>`;
 if(c.health==='losing')return `<button class="btn danger" data-action-code="campaignAction('pause','${c.id}')">${t('pause')}</button><button class="btn primary" data-action-code="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn" data-action-code="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button>`;
 return `<button class="btn" data-action-code="budgetPrompt('${c.id}',${c.daily_budget})">${t('adjust_budget')}</button><button class="btn" data-action-code="generateRefresh('${c.id}')">${t('refresh_creative')}</button><button class="btn danger" data-action-code="campaignAction('pause','${c.id}')">${t('pause')}</button>`;
}
function card(c){const accountLabel=c.account_name||c.ad_account_id||c.account_id||'';const accountNote=accountLabel?`<p class="notice">${lang==='es'?'Cuenta':'Account'}: ${escapeHtml(accountLabel)}</p>`:'';const rows=campaignPriorityRows(c);const profile=c.metric_profile||{};const profileLabel={sales:lang==='es'?'Ventas':'Sales',leads:lang==='es'?'Leads':'Leads',messages:lang==='es'?'Mensajes':'Messages',traffic:lang==='es'?'Tráfico':'Traffic',awareness:lang==='es'?'Reconocimiento':'Awareness',video:lang==='es'?'Video':'Video',app:lang==='es'?'Instalaciones':'App installs',engagement:lang==='es'?'Interacción':'Engagement',general:lang==='es'?'General':'General'}[profile.objective_type]||(lang==='es'?'General':'General');const scorecardNote=`<p class="metric-profile-note"><span>${escapeHtml(profileLabel)}</span>${profile.source==='agent'?(lang==='es'?'Priorizado por tu manager IA':'Prioritized by your AI manager'):(lang==='es'?'Adaptado al objetivo real':'Adapted to the real objective')}</p>`;const snapshot=campaignMetricSnapshot(c);const draft=lang==='es'?`Analiza la campaña ${c.name} usando sus métricas prioritarias: ${snapshot}. Contrasta primero con Meta en vivo y dime qué harías como manager.`:`Analyze campaign ${c.name} using its priority metrics: ${snapshot}. Check live Meta first and tell me what you would do as manager.`;return `<article class="card aurora-card" data-health="${c.health}"><span class="starfield" aria-hidden="true"></span><div class="top"><h3>${escapeHtml(demoCampaignName(c.name))}</h3><span class="badge ${c.health}">${statusText(c.health)}</span></div>${accountNote}${scorecardNote}<div class="metrics adaptive-metrics">${rows.map(priorityMetric).join('')}</div><div class="actions">${campaignButtons(c)}<button class="btn ask-btn" data-action-code="openChat(${JSON.stringify(draft).replaceAll('"','&quot;')})">${t('ask_agent')}</button></div></article>`}
async function campaignAction(action,campaign_id){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action,campaign_id})});const staged=res.result?.status==='pending';toast(staged?(lang==='es'?'Decisión enviada a aprobación':'Decision sent for approval'):(action==='resume'?t('toast_resume'):t('toast_action')));await load()}
async function applyRec(campaign_id,new_budget){const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'apply_recommendation',campaign_id,new_budget})});toast(res.result?.status==='pending'?(lang==='es'?'Cambio enviado a aprobación':'Change sent for approval'):t('toast_budget'));await load()}
function budgetDialog(campaign_id,current){
 const campaign=(state.metrics?.campaigns||[]).find(c=>c.id===campaign_id)||{};
 const safeCurrent=Number(current||campaign.daily_budget||0)||0;
 const suggestions=[safeCurrent,Math.round(safeCurrent*1.1),Math.round(safeCurrent*1.2)].filter((v,i,a)=>v>0&&a.indexOf(v)===i);
 const agentDraft=lang==='es'?`Revisa el presupuesto de ${campaign.name||'esta campaña'}. Está con presupuesto diario ${fmtMoney(safeCurrent)}, ROAS ${Number(campaign.roas||0).toFixed(2)}x y CPA ${fmtMoney(campaign.cpa)}. Dime cuánto pondrías y por qué antes de tocar nada.`:`Review the budget for ${campaign.name||'this campaign'}. Daily budget is ${fmtMoney(safeCurrent)}, ROAS ${Number(campaign.roas||0).toFixed(2)}x and CPA ${fmtMoney(campaign.cpa)}. Tell me what you would set and why before touching anything.`;
 const box=qs('#confirm-overlay');
 box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Ajustar presupuesto con calma':'Adjust budget calmly'}</h2><p>${lang==='es'?'Elige el nuevo máximo diario. Si no estás seguro, pregúntale al manager primero y vuelve a esta decisión después.':'Choose the new daily maximum. If you are not sure, ask the manager first and come back to this decision.'}</p><form class="unlock-form" data-submit-code="submitBudgetDialog(event,${chatArg(campaign_id)})"><label>${lang==='es'?'Nuevo presupuesto diario':'New daily budget'}<input id="budget-dialog-value" type="number" min="1" step="1" value="${safeCurrent}" inputmode="decimal"></label>${suggestions.length?`<div class="mode-actions">${suggestions.map(v=>`<button class="btn" type="button" data-action-code="qs('#budget-dialog-value').value='${v}'">${fmtMoney(v)}</button>`).join('')}</div>`:''}<p class="notice">${lang==='es'?'Si supera tus reglas, quedará en aprobación antes de tocar Meta Ads.':'If it exceeds your rules, it will go to approval before touching Meta Ads.'}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn ask-btn" type="button" data-action-code="closeConfirm();openChat(${chatArg(agentDraft)})">${lang==='es'?'Preguntar al manager':'Ask manager'}</button><button class="btn primary" type="submit">${lang==='es'?'Enviar cambio':'Send change'}</button></div></form></div>`;
 box.classList.add('open');
 setTimeout(()=>qs('#budget-dialog-value')?.focus(),30);
}
async function submitBudgetDialog(event,campaign_id){event.preventDefault();const val=Number(qs('#budget-dialog-value')?.value||0);if(!val||val<1){toast(lang==='es'?'Escribe un presupuesto mayor a cero.':'Enter a budget greater than zero.');return}closeConfirm();const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'adjust_budget',campaign_id,new_budget:val})});toast(res.result?.status==='pending'?(lang==='es'?'Cambio enviado a aprobación':'Change sent for approval'):t('toast_budget'));await load()}
async function budgetPrompt(campaign_id,current){budgetDialog(campaign_id,current)}
async function runAgent(){await api('/api/action',{method:'POST',body:JSON.stringify({action:'run_agent'})});toast(t('toast_daily'));await load()}
let liveMetricsRefreshInFlight=false;
let liveMetricsAutoTimer=null;
let liveMetricsLastRefreshAt=0;
const LIVE_METRICS_REFRESH_MS=2*60*1000;
async function refreshInsights(options={}){if(liveMetricsRefreshInFlight)return null;liveMetricsRefreshInFlight=true;try{const refreshScope=options.scope||(options.silent?'dashboard_live':'full');const selected=normalizeClientMetricsRange(options.range||metricsRange);document.querySelector('.metrics-range-bar')?.classList.add('loading');const res=await api('/api/action',{method:'POST',body:JSON.stringify({action:'refresh_insights',refresh_scope:refreshScope,date_preset:selected.preset,since:selected.since,until:selected.until})});if(!options.silent){if(res.result&&res.result.ok){toast(lang==='es'?`Métricas actualizadas: ${metricsRangeText(selected)}.`:`Metrics updated: ${metricsRangeText(selected)}.`)}else{toast(lang==='es'?'No pude leer datos reales todavía. Revisa tu clave de Meta y la cuenta elegida.':'Could not read real data yet. Check your Meta key and chosen account.')}}if(res.result&&res.result.ok){metricsRange=selected;liveMetricsLastRefreshAt=Date.now();await load()}return res}finally{liveMetricsRefreshInFlight=false;document.querySelector('.metrics-range-bar')?.classList.remove('loading')}}
function startLiveMetricsAutoRefresh(){if(uiWorkbenchPreview||liveMetricsAutoTimer)return;const refreshVisible=()=>{if(document.visibilityState==='visible')refreshInsights({silent:true,scope:'dashboard_live'})};liveMetricsAutoTimer=setInterval(refreshVisible,LIVE_METRICS_REFRESH_MS);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&Date.now()-liveMetricsLastRefreshAt>LIVE_METRICS_REFRESH_MS/2)refreshVisible()})}
async function exportCsv(){const r=await api('/api/export');toast(t('toast_export')+r.path)}
async function approvePending(id){const item=(state.pending||[]).find(p=>p.id===id);if(item&&item.type==='create_campaign'&&item.payload?.final_status==='ACTIVE'){const ok=await showDecisionConfirm({title:lang==='es'?'Esta campaña puede empezar a gastar':'This campaign can start spending',body:lang==='es'?'Al aprobar, se creará o encenderá como ACTIVA y podrá usar el presupuesto elegido. Revisa esto como si le dieras luz verde a un manager humano.':'When approved, it will be created or turned on as ACTIVE and may use the selected budget. Review this like giving a human manager the green light.',items:[item.payload?.name||item.payload?.campaign_name||item.type,lang==='es'?'La aprobación debe salir de un botón exacto o de una frase exacta; el agente no puede decidir solo.':'Approval must come from an exact button or exact phrase; the agent cannot decide alone.'],confirmLabel:lang==='es'?'Sí, aprobar activa':'Yes, approve active',agentDraft:lang==='es'?`Explícame esta aprobación de campaña activa antes de que yo decida. ¿Qué riesgo tiene y qué debería revisar?`:`Explain this active campaign approval before I decide. What is the risk and what should I review?`});if(!ok)return []}const res=await api('/api/approve',{method:'POST',body:JSON.stringify({approval_id:id})});const attempted=(res.result||[])[0]||{};toast(attempted.status==='approved'?t('toast_approval'):(lang==='es'?'No se pudo ejecutar. La decisión sigue pendiente para reintentar.':'Execution failed. The decision remains pending so you can retry.'));await load();return res.result||[]}
async function setMode(mode){
 await api('/api/mode',{method:'POST',body:JSON.stringify({mode:'approval'})});
 toast(lang==='es'?'Protección por aprobación activa':'Approval protection active');
 await load();
}
async function setLocalNetworkAccess(enabled){
 const box=qs('#local-network-panel');
 if(box)box.insertAdjacentHTML('afterbegin',`<div class="guide-card"><p>${enabled?(lang==='es'?'Preparando enlace para tu teléfono...':'Preparing phone link...'):(lang==='es'?'Apagando acceso por Wi‑Fi...':'Turning off Wi‑Fi access...')}</p></div>`);
 const res=await api('/api/local-network-access',{method:'POST',body:JSON.stringify({enabled})});
 const result=res.result||res;
 if(result.restarting){
  toast(enabled?(lang==='es'?'Activando acceso por Wi‑Fi. El dashboard se reiniciará.':'Turning on Wi‑Fi access. The dashboard will restart.'):(lang==='es'?'Apagando acceso por Wi‑Fi. El dashboard se reiniciará.':'Turning off Wi‑Fi access. The dashboard will restart.'));
  setTimeout(()=>window.location.reload(),2200);
  return;
 }
 toast(enabled?(lang==='es'?'Acceso para teléfono activado.':'Phone access enabled.'):(lang==='es'?'Acceso por Wi‑Fi apagado.':'Wi‑Fi access turned off.'));
 await load();
}
async function saveGuardrails(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());data.require_approval_for_resume=form.require_approval_for_resume.checked;data.require_approval_for_new_campaigns=form.require_approval_for_new_campaigns.checked;data.require_approval_for_creatives=form.require_approval_for_creatives.checked;await api('/api/guardrails',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Reglas guardadas':'Rules saved');await load()}
async function saveProfitabilityRules(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());await api('/api/profitability-rules',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Reglas de rentabilidad guardadas':'Profitability rules saved');await load()}
async function saveOptimizationSettings(e){e.preventDefault();const data=Object.fromEntries(new FormData(e.target).entries());await api('/api/optimization/settings',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Optimización guardada':'Optimization saved');await load()}
async function unlockOptimization(){await api('/api/optimization/unlock',{method:'POST',body:JSON.stringify({confirm:true})});toast(lang==='es'?'Optimizador desbloqueado con tus límites':'Optimizer unlocked within your limits');await load()}
let publishingTokenAutoSaveTimer=null;
let publishingTokenSaving=false;
let lastPublishingTokenSaved='';
function schedulePublishingTokenAutoSave(event){
 if(event?.type==='paste'){setTimeout(()=>schedulePublishingTokenAutoSave(),0);return}
 clearTimeout(publishingTokenAutoSaveTimer);
 const token=(qs('#meta-publishing-token-input')?.value||'').trim();
 if(token.length<20||token===lastPublishingTokenSaved)return;
 publishingTokenAutoSaveTimer=setTimeout(()=>savePublishingTokenAutomatically(token),500);
}
async function savePublishingTokenAutomatically(token){
 const input=qs('#meta-publishing-token-input');
 const value=String(token||input?.value||'').trim();
 if(value.length<20||publishingTokenSaving||value===lastPublishingTokenSaved)return;
 publishingTokenSaving=true;
 lastPublishingTokenSaved=value;
 if(input){input.disabled=true;input.placeholder=lang==='es'?'Guardando token...':'Saving token...'}
 try{
  const result=await api('/api/publishing/config',{method:'POST',body:JSON.stringify({token:value})});
  if(input){input.value='';input.placeholder=lang==='es'?'Token de página guardado':'Page token saved'}
  toast(result.message||(lang==='es'?'Token de página guardado.':'Page token saved.'));
  await load();
 }catch(err){
  lastPublishingTokenSaved='';
  if(input)input.placeholder=lang==='es'?'Revisa el token e intenta otra vez':'Check the token and try again';
  toast(err.message||String(err));
 }finally{
  publishingTokenSaving=false;
  if(input)input.disabled=false;
 }
}
async function savePublishingConfig(e){e.preventDefault();const data=Object.fromEntries(new FormData(e.target).entries());if(!String(data.token||'').trim()){toast(lang==='es'?'Pega la clave de publicación primero.':'Paste the publishing key first.');return}const res=await api('/api/publishing/config',{method:'POST',body:JSON.stringify(data)});toast(res.message||(res.ok?(lang==='es'?'Publicación directa lista':'Direct publishing ready'):(lang==='es'?'Clave guardada, pero falta revisar permisos':'Key saved, but permissions need review')));await load()}
async function testPublishingConnection(){const res=await api('/api/publishing/test',{method:'POST',body:'{}'});toast(res.message||(res.ok?(lang==='es'?'Publicación directa lista':'Direct publishing ready'):(lang==='es'?'Publicación directa no está lista':'Direct publishing is not ready')))}
async function disconnectPublishingConfig(){const ok=await showDecisionConfirm({title:lang==='es'?'Desconectar publicación directa':'Disconnect direct publishing',body:lang==='es'?'El agente dejará de publicar posts o crear creativos nativos hasta conectar otra clave. Las campañas y datos guardados no se borran.':'The agent will stop publishing posts or creating native-post creatives until another key is connected. Saved campaigns and data are not deleted.',confirmLabel:lang==='es'?'Desconectar':'Disconnect'});if(!ok)return;await api('/api/publishing/config',{method:'POST',body:JSON.stringify({disconnect:true})});toast(lang==='es'?'Publicación directa desconectada':'Direct publishing disconnected');await load()}
async function saveShopifyConfig(e){e.preventDefault();const data=Object.fromEntries(new FormData(e.target).entries());await api('/api/shopify/config',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Shopify guardado':'Shopify saved');await load()}
async function testShopifyConnection(){const res=await api('/api/shopify/test',{method:'POST',body:'{}'});toast(res.ok?(lang==='es'?'Shopify conectado correctamente':'Shopify connected'):(lang==='es'?'No pude conectar Shopify':'Could not connect Shopify'))}
async function syncShopifyOutcomes(){const res=await api('/api/shopify/sync',{method:'POST',body:'{}'});toast(lang==='es'?`Sincronizados ${res.orders_seen||0} pedidos sin datos personales`:`Synced ${res.orders_seen||0} orders without personal data`);await load()}
async function saveTelegramConfig(e){e.preventDefault();const form=e.target;const data=Object.fromEntries(new FormData(form).entries());data.enabled=form.enabled.checked;const fromOnboarding=qs('#onboarding-flow')?.classList.contains('open');await api('/api/telegram/config',{method:'POST',body:JSON.stringify(data)});toast(lang==='es'?'Telegram guardado':'Telegram saved');await load();if(fromOnboarding)await maybeFinishTelegramOnboarding()}
async function fetchProtectedFile(path,opts={}){
 const headers={...(opts.headers||{})};const password=dashboardPassword();if(password)headers['X-Dashboard-Token']=password;
 let res=await fetch(path,{...opts,headers});
 if(res.status===401){clearStoredDashboardSecrets();const entered=await requestUnlock();if(entered){headers['X-Dashboard-Token']=entered;res=await fetch(path,{...opts,headers})}}
 if(!res.ok)throw new Error(await responseErrorMessage(res));
 return res;
}
async function downloadMigrationBackup(){
 const box=qs('#migration-result');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Preparando respaldo seguro...':'Preparing secure backup...'}</p></div>`;
 try{
  const res=await fetchProtectedFile('/api/migration/export',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const blob=await res.blob();const disposition=res.headers.get('Content-Disposition')||'';const match=disposition.match(/filename="([^"]+)"/);const filename=match?match[1]:'meta-ads-agent-respaldo.tar.gz';
  const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Respaldo creado':'Backup created'}</b><p>${lang==='es'?'Se descargó el archivo. Guárdalo en un lugar privado.':'The file downloaded. Store it somewhere private.'}</p></div>`;
 }catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude crear el respaldo':'Could not create backup'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
let pendingMigrationFile=null;
function restoreMigrationBackup(event){
 const file=event.target.files&&event.target.files[0];event.target.value='';
 if(!file)return;pendingMigrationFile=file;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Restaurar respaldo':'Restore backup'}</h2><p>${lang==='es'?'Voy a reemplazar la memoria local de este dashboard por el respaldo seleccionado. Haré una copia interna de lo actual antes de restaurar.':'I will replace this dashboard local memory with the selected backup. I will make an internal copy of the current state before restoring.'}</p><p class="notice">${escapeHtml(file.name)} · ${Math.round(file.size/1024)} KB</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="pendingMigrationFile=null;closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" data-action-code="confirmMigrationRestore()">${lang==='es'?'Restaurar':'Restore'}</button></div></div>`;box.classList.add('open');
}
function arrayBufferToBase64(buffer){let binary='';const bytes=new Uint8Array(buffer);const chunk=0x8000;for(let i=0;i<bytes.length;i+=chunk){binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+chunk))}return btoa(binary)}
async function confirmMigrationRestore(){
 const file=pendingMigrationFile;pendingMigrationFile=null;closeConfirm();if(!file)return;
 const box=qs('#migration-result');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Restaurando respaldo...':'Restoring backup...'}</p></div>`;
 try{
  const content_base64=arrayBufferToBase64(await file.arrayBuffer());
  const res=await api('/api/migration/import',{method:'POST',body:JSON.stringify({filename:file.name,content_base64})});
  const restored=(res.result?.restored||[]).join(', ');
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Respaldo restaurado':'Backup restored'}</b><p>${escapeHtml(res.result?.message||'')}</p><p class="notice">${escapeHtml(restored)}</p></div>`;
  toast(lang==='es'?'Respaldo restaurado':'Backup restored');await load();
 }catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude restaurar':'Could not restore'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
async function refreshCloudAccess(){
 const box=qs('#cloud-access-result');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Permitiendo que abras tu dashboard desde esta red...':'Allowing dashboard access from this network...'}</p></div>`;
 try{
  const res=await api('/api/cloud-access/refresh',{method:'POST',body:'{}'});
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Esta red ya puede entrar':'This network can now enter'}</b><p>${lang==='es'?'Ya puedes abrir el dashboard desde este lugar.':'You can now open the dashboard from this location.'}</p></div>`;
  toast(lang==='es'?'Acceso listo para esta red':'Access ready for this network');
 }catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude actualizar el acceso':'Could not refresh access'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
function updateSnapshotMarkup(items){
 if(!items||!items.length)return `<div class="guide-card"><p class="notice">${lang==='es'?'Todavía no hay copias guardadas. Se crearán automáticamente antes de la próxima actualización oficial.':'No saved copies yet. They will be created automatically before the next official update.'}</p></div>`;
 return `<div class="update-cards">${items.map(item=>`<div class="update-card"><span>${escapeHtml(item.channel||'stable')}</span><b>${escapeHtml(item.version||'')}</b><p>${escapeHtml(new Date(item.created_at||Date.now()).toLocaleString())}</p><button class="btn" type="button" data-action-code="confirmUpdateRollback('${escapeHtml(item.id||'')}')">${lang==='es'?'Volver a esta versión':'Restore this version'}</button></div>`).join('')}</div>`;
}
async function loadUpdateSnapshots(force=false){
 const box=qs('#update-snapshot-list');if(!box)return;
 if(force)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando copias guardadas...':'Looking for saved copies...'}</p></div>`;
 try{const res=await api('/api/update/snapshots');box.innerHTML=updateSnapshotMarkup(res.result||[])}catch(err){if(force)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude leer las copias':'Could not read saved copies'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`}
}
function confirmUpdateRollback(snapshotId){
 if(!snapshotId)return;
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Volver a una versión anterior':'Restore previous version'}</h2><p>${lang==='es'?'Voy a devolver el dashboard a esta copia guardada. Esto no deshace cambios que Meta ya haya realizado en campañas activas.':'I will return the dashboard to this saved copy. This does not undo changes Meta already made to active campaigns.'}</p><p class="notice">${escapeHtml(snapshotId)}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" data-action-code="rollbackUpdateSnapshot('${escapeHtml(snapshotId)}')">${lang==='es'?'Volver ahora':'Restore now'}</button></div></div>`;box.classList.add('open');
}
async function rollbackUpdateSnapshot(snapshotId){
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Volviendo a la versión elegida':'Restoring'}</h2><p>${lang==='es'?'Estoy usando la copia guardada y conservando una copia de lo que tienes ahora.':'Restoring the saved copy and keeping a copy of what you have now.'}</p></div>`;box.classList.add('open');
 try{const res=await api('/api/update/rollback',{method:'POST',body:JSON.stringify({snapshot_id:snapshotId})});box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Versión lista':'Version restored'}</h2><p>${escapeHtml(res.result?.message||'')}</p><p class="notice">${lang==='es'?'Copia de lo anterior':'Backup of previous state'}: ${escapeHtml(res.result?.rescue_snapshot_id||'')}</p></div>`;toast(lang==='es'?'Ya estás usando la versión anterior':'Previous version restored')}catch(err){box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'No pude volver a esa versión':'Could not restore'}</h2><p>${escapeHtml(err.message||String(err))}</p><div class="confirm-actions"><button class="btn primary" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cerrar':'Close'}</button></div></div>`}
}
async function finishOnboardingAndStartTour(reason='manual',communicationStyle=''){
 try{
  const payload={};if(communicationStyle)payload.communication_style=communicationStyle;
  await api('/api/onboarding/complete',{method:'POST',body:JSON.stringify(payload)});
  if(reason!=='telegram'){
   localStorage.setItem('dashboardIntroTourPending','1');
   localStorage.removeItem('dashboardIntroTourDone');
  }else{
   localStorage.removeItem('dashboardIntroTourPending');
   localStorage.setItem('dashboardIntroTourDone','1');
  }
  toast(reason==='telegram'?(lang==='es'?'Telegram listo. Te muestro el dashboard.':'Telegram ready. Showing the dashboard.'):(lang==='es'?'Configuración inicial terminada. Te muestro el dashboard.':'Initial setup complete. Showing the dashboard.'));
  await load();
  if(reason!=='telegram')setTimeout(startDashboardIntroTourIfPending,500);
  return true;
 }catch(err){
  toast(err.message||String(err));
  await load();
  return false;
 }
}
let telegramHelloPollTimer=null;
let telegramHelloPollBusy=false;
function stopTelegramHelloPolling(){
 if(telegramHelloPollTimer)clearTimeout(telegramHelloPollTimer);
 telegramHelloPollTimer=null;
 telegramHelloPollBusy=false;
}
function startTelegramHelloPolling(){
 const flow=qs('#onboarding-flow');
 const telegram=state.config?.telegram_agent||{};
 if(!flow?.classList.contains('open')||!telegram.bot_configured||telegram.chat_id){stopTelegramHelloPolling();return}
 if(telegramHelloPollTimer||telegramHelloPollBusy)return;
 telegramHelloPollTimer=setTimeout(async()=>{
  telegramHelloPollTimer=null;
  if(telegramHelloPollBusy)return;
  telegramHelloPollBusy=true;
  try{await detectTelegramChats({silent:true})}catch(_err){}finally{
   telegramHelloPollBusy=false;
   const current=state.config?.telegram_agent||{};
   if(qs('#onboarding-flow')?.classList.contains('open')&&current.bot_configured&&!current.chat_id)startTelegramHelloPolling();
  }
 },2200);
}
async function maybeFinishTelegramOnboarding(){
 const telegram=state.config?.telegram_agent||{};
 if(telegram.enabled&&telegram.bot_configured&&telegram.chat_id){
  const steps=onboardingSteps();
  if(steps.every(step=>step.status==='ok')){
   stopTelegramHelloPolling();
   return finishOnboardingAndStartTour('telegram');
  }
  renderOnboardingFlow();
 }
 return false;
}
async function detectTelegramChats(options={}){
 const silent=Boolean(options?.silent);
 const box=qs('#telegram-results');if(box&&!silent)box.innerHTML=`<div class="telegram-next-action"><div class="telegram-orb">...</div><div><b>${lang==='es'?'Buscando tu hola':'Looking for your hello'}</b><p>${lang==='es'?'Estoy revisando los mensajes recientes del bot.':'I am checking the bot recent messages.'}</p></div></div>`;
 const res=await api('/api/telegram/detect',{method:'POST',body:'{}'});const rows=res.result||[];
 if(!box)return;
 if(!rows.length){if(!silent)box.innerHTML=`<div class="telegram-next-action"><div class="telegram-orb">AI</div><div><b>${lang==='es'?'Todavía no veo tu mensaje':'I do not see your message yet'}</b><p>${lang==='es'?'Abre Telegram, entra al bot que creaste, envíale "hola" y vuelve a tocar detectar.':'Open Telegram, enter the bot you created, send "hello", and tap detect again.'}</p></div><button class="btn primary telegram-detect-button" type="button" data-action-code="detectTelegramChats()">${lang==='es'?'Ya envié hola, intentar otra vez':'I sent hello, try again'}</button></div>`;return []}
 const chat=rows[rows.length-1]||rows[0]||{};
 const chatId=String(chat.id||'').trim();
 if(!chatId){if(!silent)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude leer el chat':'Could not read the chat'}</b><p>${lang==='es'?'Vuelve a enviar "hola" al bot e intenta otra vez.':'Send "hello" to the bot again and try once more.'}</p></div>`;return []}
 box.innerHTML=`<div class="telegram-next-action ready"><div class="telegram-orb">✓</div><div><b>${lang==='es'?'Detecté tu chat':'I found your chat'}</b><p>${lang==='es'?'Lo estoy conectando y te enviaré el primer mensaje.':'I am connecting it and sending the first message.'}</p></div></div>`;
 try{
  await selectTelegramChat(chatId,qs('#onboarding-flow')?.classList.contains('open'));
 }catch(err){
  box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude guardar el chat':'Could not save the chat'}</b><p>${escapeHtml(err.message||String(err))}</p><button class="btn primary telegram-detect-button" type="button" data-action-code="detectTelegramChats()">${lang==='es'?'Intentar otra vez':'Try again'}</button></div>`;
 }
 return rows;
}
async function selectTelegramChat(id,fromOnboarding=false){
 const payload=fromOnboarding?{chat_id:id,enabled:'true',send_welcome:'true'}:{chat_id:id,send_welcome:'true'};
 const status=await api('/api/telegram/config',{method:'POST',body:JSON.stringify(payload)});
 const welcomeSent=Boolean(status?.result?.welcome_sent||status?.welcome_sent);
 toast(welcomeSent?(lang==='es'?'Chat guardado. Te envié el primer mensaje.':'Chat saved. I sent you the first message.'):(lang==='es'?'Chat de Telegram guardado':'Telegram chat saved'));
 await load();
 if(fromOnboarding){const finished=await maybeFinishTelegramOnboarding();if(finished)return;renderOnboardingFlow()}
}
async function testTelegram(){await api('/api/telegram/test',{method:'POST',body:'{}'});toast(lang==='es'?'Mensaje enviado a Telegram':'Test message sent to Telegram')}
function showDetails(campaign_id){const c=state.metrics.campaigns.find(item=>item.id===campaign_id);if(c)toast(`${t('details')}: ${demoCampaignName(c.name)} · ${campaignMetricSnapshot(c)}`);else toast(t('toast_details'))}
function initBrandGuides(){
 const suggested=state.business_profile?.main_offer||state.business_profile?.offer||'';
 const draft=lang==='es'?'Ayúdame a definir mi producto principal y mi guía de marca para crear anuncios consistentes. Hazme preguntas fáciles, una por una.':'Help me define my main product and brand guide for consistent ads. Ask simple questions one at a time.';
 const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Crear memoria de marca':'Create brand memory'}</h2><p>${lang==='es'?'Escribe el producto u oferta principal. Si no sabes cómo resumirlo, háblalo con el agente y él te guía.':'Enter the main product or offer. If you are not sure how to summarize it, talk to the agent and it will guide you.'}</p><form class="unlock-form" data-submit-code="submitBrandGuideInit(event)"><label>${lang==='es'?'Producto u oferta principal':'Main product or offer'}<input id="brand-guide-init-name" value="${escapeHtml(suggested)}" placeholder="${lang==='es'?'Ej: curso de uñas, ecommerce de ropa, clínica dental':'Ex: nail course, clothing store, dental clinic'}"></label><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn ask-btn" type="button" data-action-code="closeConfirm();openChat(${chatArg(draft)})">${lang==='es'?'Hablarlo con el agente':'Talk with agent'}</button><button class="btn primary" type="submit">${lang==='es'?'Crear memoria':'Create memory'}</button></div></form></div>`;box.classList.add('open');setTimeout(()=>qs('#brand-guide-init-name')?.focus(),30)
}
async function submitBrandGuideInit(event){event.preventDefault();const name=(qs('#brand-guide-init-name')?.value||'').trim();if(!name){toast(lang==='es'?'Escribe el nombre de tu producto u oferta.':'Enter your product or offer name.');return}closeConfirm();await api('/api/brand-guides/init',{method:'POST',body:JSON.stringify({product_name:name})});toast(lang==='es'?'Guías de marca creadas.':'Brand guides created.');await load()}
async function generateRefresh(campaign_id='',product_guide='',ad_brief=''){
 const products=state.brand_guides?.products||[];const adBriefs=state.brand_guides?.ad_briefs||[];
 if(!campaign_id&&!product_guide&&!ad_brief&&adBriefs.length===1)ad_brief=adBriefs[0].guide;
 if(!campaign_id&&!product_guide&&!ad_brief&&adBriefs.length>1){openBrandMemory('ad_brief',adBriefs[0].id);toast(lang==='es'?'Elige la idea de anuncio que quieres trabajar':'Choose the ad idea to work on');return}
 if(!campaign_id&&!product_guide&&products.length===1)product_guide=products[0].guide;
 if(!campaign_id&&!product_guide&&products.length>1){openBrandMemory('product',products[0].id);toast(lang==='es'?'Elige el producto para crear propuestas coherentes':'Choose a product for consistent proposals');return}
 const payload={};if(campaign_id)payload.campaign_id=campaign_id;if(product_guide)payload.product_guide=product_guide;if(ad_brief)payload.ad_brief=ad_brief;
 await api('/api/creative-refresh',{method:'POST',body:JSON.stringify(payload)});toast(t('toast_refresh'));await load();
}
async function stageUpload(manifest_path,variant_id,ratios=['1:1']){await api('/api/stage-upload',{method:'POST',body:JSON.stringify({manifest_path,variant_id,ratios:ratios.length?ratios:['1:1']})});toast(lang==='es'?'Imagen lista para que la apruebes. También quedó guardada como pieza de anuncio.':'Image sent for approval. It was also saved as an ad asset.');await load()}
async function buildAudienceStrategy(payload){const res=await api('/api/audience-strategy',{method:'POST',body:JSON.stringify({...payload,language:lang})});state.audience_strategy=res.result;renderAudience();toast(t('toast_audience'))}
let pendingBusinessReplacement=null;
function needsBusinessReplacement(err){return String(err?.message||err||'').includes('CONFIRM_BUSINESS_REPLACE')}
function showBusinessReplacementConfirm(payload){
 pendingBusinessReplacement=payload;
 const box=qs('#confirm-overlay');
 const agency=Boolean(state?.license_entitlements?.is_agency||state?.config?.license_entitlements?.is_agency);
 const title=agency?(lang==='es'?'Cambiar de Business Manager':'Change Business Manager'):(lang==='es'?'Cambiar de negocio':'Change business');
 const body=agency?(lang==='es'?'La cuenta pertenece a otro Business Manager. Confirma para reemplazar el negocio activo de esta instalación y continuar con la nueva cuenta.':'This account belongs to another Business Manager. Confirm to replace the active business for this installation and continue with the new account.'):(lang==='es'?'Tu licencia Individual cuida un solo negocio activo. Si cambias de negocio, empezamos limpio para evitar mezclar datos.':'Your Individual license protects one active business. If you switch business, we start clean to avoid mixing data.');
 const notice=agency?(lang==='es'?'Se actualizará la cuenta y el registro de negocio de esta instalación. No se borra tu licencia ni tus credenciales.':'This installation’s account and business registry will be updated. Your license and credentials are not deleted.'):(lang==='es'?'Esto borra memoria del agente, métricas guardadas, chat, actividad, guías creativas e imágenes de trabajo del negocio anterior. No borra tu licencia, email, contraseña ni este equipo.':'This removes agent memory, saved metrics, chat, creative guides, and working images for the previous business. It does not remove your license, email, password, or this device.');
 box.innerHTML=`<div class="confirm-card"><h2>${title}</h2><p>${body}</p><p class="notice">${notice}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="pendingBusinessReplacement=null;closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" data-action-code="confirmBusinessReplacement()">${lang==='es'?'Cambiar y seguir':'Change and continue'}</button></div></div>`;box.classList.add('open')
}
async function confirmBusinessReplacement(){const pending={...(pendingBusinessReplacement||{})};pendingBusinessReplacement=null;closeConfirm();const isAccountSwitch=pending._meta_flow==='social_account';delete pending._meta_flow;const payload={...pending,confirm_replace_business:true};if(isAccountSwitch){await selectSocialAccount(payload);return}await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Nuevo negocio guardado. Empezamos con memoria limpia.':'New business saved. Starting with clean memory.');await load()}
async function saveSetupPayload(payload,advance=false){try{await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(t('toast_setup_saved'));await load();if(advance)advanceOnboardingAfterLoad()}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm(payload);return}throw err}}
async function saveSetupConfig(e){
 e.preventDefault();
 const payload=Object.fromEntries(new FormData(e.target).entries());
 if(e.submitter?.name==='agent_model_action')payload.agent_model_action=e.submitter.value;
 await saveSetupPayload(payload);
}
async function saveOnboardingSetupConfig(e){e.preventDefault();await saveSetupPayload(Object.fromEntries(new FormData(e.target).entries()),true)}
async function createAgencySpace(e){e.preventDefault();toast(lang==='es'?'Esta opción no está disponible en esta edición.':'This option is not available in this edition.')}
async function switchAgencySpace(id){await api('/api/agency/spaces/switch',{method:'POST',body:JSON.stringify({space_id:id})});toast(lang==='es'?'Cliente activo cambiado.':'Active client changed.');await load()}
async function saveBusinessLinks(e){
 e.preventDefault();
 const payload=Object.fromEntries(new FormData(e.target).entries());
 const box=qs('#business-scan-results');
 if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Guardando links para que el agente los revise...':'Saving links for the agent to review...'}</p></div>`;
 try{
  const res=await api('/api/business-profile/links',{method:'POST',body:JSON.stringify(payload)});
  toast(lang==='es'?'Listo. El agente usará esto para entrevistarte por Telegram.':'Ready. The agent will use this when interviewing you through Telegram.');
  await load();
  const steps=onboardingSteps();
  const idx=steps.findIndex(s=>s.id==='telegram');
  onboardingFlowTouched=true;
  onboardingFlowStep=idx>=0?idx:onboardingFlowStep;
  renderOnboardingFlow();
  return res;
 }catch(err){
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude guardar esos links':'I could not save those links'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;
  throw err;
 }
}
async function startBusinessInterview(e){
 e.preventDefault();
 const payload=Object.fromEntries(new FormData(e.target).entries());
 payload.language=lang;
 const business=String(payload.business_type||'').trim();
 if(!business){toast(lang==='es'?'Escribe tu negocio en pocas palabras.':'Write your business in a few words.');return}
 const box=qs('#business-scan-results');
 if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Preparando preguntas...':'Preparing questions...'}</p></div>`;
 try{
  const res=await api('/api/business-profile/questions',{method:'POST',body:JSON.stringify(payload)});
  toast(lang==='es'?'Listo. Ahora vamos pregunta por pregunta.':'Ready. Now we go one question at a time.');
  await load();
  businessContextQuestionIndex=0;
  const steps=onboardingSteps();
  const idx=steps.findIndex(s=>s.id==='context');
  onboardingFlowTouched=true;
  onboardingFlowStep=idx>=0?idx:onboardingFlowStep;
  renderOnboardingFlow();
  return res;
 }catch(err){
  if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude preparar las preguntas':'Could not prepare the questions'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;
  throw err;
 }
}
async function scanBusinessWebsite(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());const box=qs('#business-scan-results');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Leyendo tu web y preparando respuestas sugeridas...':'Reading your website and preparing suggested answers...'}</p></div>`;try{const res=await api('/api/business-profile/scan',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Web analizada. Ahora revisamos una respuesta a la vez.':'Website scanned. Now we review one answer at a time.');await load();businessContextQuestionIndex=0;const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='context');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow();return res}catch(err){if(box)box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude leer la web todavía':'I could not read the website yet'}</b><p>${escapeHtml(err.message||String(err))}</p></div>`;throw err}}
async function skipWebsiteScan(){await api('/api/business-profile/links',{method:'POST',body:JSON.stringify({website_skipped:true})});toast(lang==='es'?'Perfecto. El agente te preguntará lo necesario después.':'Perfect. The agent will ask what it needs later.');await load();const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='telegram');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow()}
function setBusinessContextQuestionIndex(index){const questions=businessContextQuestions();businessContextQuestionIndex=Math.max(0,Math.min(Number(index)||0,questions.length-1));renderOnboardingFlow()}
async function saveBusinessContextQuestion(e){e.preventDefault();const form=e.target;const field=String(new FormData(form).get('field')||'').trim();const answer=String(new FormData(form).get('answer')||'').trim();if(!field||!answer){toast(lang==='es'?'Escribe una respuesta corta para seguir.':'Write a short answer to continue.');return}const questions=businessContextQuestions();const idx=Math.max(0,questions.findIndex(q=>q.key===field));const isLast=idx>=questions.length-1;const payload={[field]:answer};if(isLast)payload.context_complete=true;await api('/api/business-profile',{method:'POST',body:JSON.stringify(payload)});await load();if(isLast){toast(lang==='es'?'Contexto listo. Te muestro el primer plan.':'Context ready. Showing the first plan.');const steps=onboardingSteps();const strategyIndex=steps.findIndex(s=>s.id==='strategy');onboardingFlowTouched=true;onboardingFlowStep=strategyIndex>=0?strategyIndex:onboardingFlowStep}else{toast(lang==='es'?'Respuesta guardada. Vamos con la siguiente.':'Answer saved. On to the next one.');businessContextQuestionIndex=Math.min(idx+1,questions.length-1)}renderOnboardingFlow()}
async function saveBusinessContext(e){e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());payload.context_complete=true;await api('/api/business-profile',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Contexto guardado. Te muestro el primer plan.':'Context saved. Showing the first plan.');await load();const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='strategy');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:onboardingFlowStep;renderOnboardingFlow()}
function showMetaTokenBox(kind='stable'){
 metaTokenKind=['stable','quick'].includes(kind)?kind:(metaTokenKind||'stable');
 const box=qs('#meta-token-box');if(!box)return;
 box.classList.add('open');
 if(box.dataset.attentionTimer)clearTimeout(Number(box.dataset.attentionTimer));
 box.classList.remove('token-box-attention');
 void box.offsetWidth;
 box.classList.add('token-box-attention');
 const reduce=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
 setTimeout(()=>{
  box.scrollIntoView({behavior:reduce?'auto':'smooth',block:'center'});
  const input=qs('#meta-token-input');
  try{input?.focus({preventScroll:true})}catch(_){input?.focus()}
 },40);
 box.dataset.attentionTimer=String(setTimeout(()=>{box.classList.remove('token-box-attention');delete box.dataset.attentionTimer},4200));
}
function goToMetaTokenStep(reason='',output=''){const steps=onboardingSteps();const idx=steps.findIndex(s=>s.id==='meta');onboardingFlowTouched=true;onboardingFlowStep=idx>=0?idx:1;renderOnboardingFlow();setTimeout(()=>{showMetaTokenBox();const box=qs('#social-account-results');if(box&&reason==='expired'){box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Pega una clave nueva':'Paste a new key'}</b><p>${lang==='es'?'Meta rechazó la clave anterior porque venció o ya no sirve. Pega aquí la clave nueva; el dashboard la guarda automáticamente y después vuelve a buscar tus cuentas.':'Meta rejected the previous key because it expired or is no longer valid. Paste the new key here; the dashboard saves it automatically and then finds your accounts again.'}</p><p class="notice">${lang==='es'?'Cuando pegas una clave válida, queda guardada localmente en este computador o VPS. No se guarda en cookies del navegador.':'When you paste a valid key, it is stored locally on this computer or VPS. It is not stored in browser cookies.'}</p>${output?`<details class="helper-command"><summary>${lang==='es'?'Detalles técnicos':'Technical details'}</summary><span class="step-command">${escapeHtml(String(output).slice(0,900))}</span></details>`:''}</div>`}},0)}
function connectMetaStarted(kind='stable'){showMetaTokenBox(kind);toast(lang==='es'?'Meta Business se abrirá en otra pestaña. Sigue la guía y pega aquí tu clave estable.':'Meta Business will open in another tab. Follow the guide and paste your stable key here.')}
let metaTokenAutoSaveTimer=null;
let metaTokenSaving=false;
let lastMetaTokenSaved='';
let metaTokenKind='unknown';
function renderTokenSavedState(kind=metaTokenKind){const tokenBox=qs('#meta-token-box');if(tokenBox){const quick=kind==='quick';const detail=lang==='es'?(quick?'Clave rápida guardada. Te avisaré si toca renovarla aproximadamente cada 60 días. Más adelante puedes cambiar a clave estable desde Configuración.':'Clave estable guardada. Esta es la conexión recomendada para trabajar todos los días.'):(quick?'Quick key saved. I will remind you if it needs renewal about every 60 days. You can switch to a stable key later from Setup.':'Stable key saved. This is the recommended connection for daily use.');tokenBox.innerHTML=`<div class="guide-card"><b>${lang==='es'?'Clave de Meta guardada':'Meta key saved'}</b><p>${escapeHtml(detail)}</p><p>${lang==='es'?'Ahora buscaré tus cuentas publicitarias.':'I will now find your ad accounts.'}</p><button class="btn" type="button" data-action-code="goToMetaTokenStep()">${lang==='es'?'Cambiar clave de Meta':'Change Meta key'}</button></div>`;tokenBox.classList.add('open')}}
function scheduleMetaTokenAutoSave(){clearTimeout(metaTokenAutoSaveTimer);const token=(qs('#meta-token-input')?.value||'').trim();if(token.length<20||token===lastMetaTokenSaved)return;metaTokenAutoSaveTimer=setTimeout(()=>saveMetaToken({auto:true}),500)}
async function saveMetaToken(options={}){const auto=Boolean(options.auto);const input=qs('#meta-token-input');const token=(input?.value||'').trim();const box=qs('#social-account-results');if(!token){if(!auto)toast(lang==='es'?'Pega primero la clave de Meta.':'Paste the Meta key first.');return}if(token.length<20){if(!auto)toast(lang==='es'?'Esa clave se ve muy corta. Revisa que la pegaste completa.':'That key looks too short. Check that you pasted the full value.');return}if(metaTokenSaving||token===lastMetaTokenSaved)return;metaTokenSaving=true;lastMetaTokenSaved=token;if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Guardando conexión local...':'Saving local connection...'}</p></div>`;try{const res=await api('/api/social/token',{method:'POST',body:JSON.stringify({token,token_kind:metaTokenKind})});const result=res.result||res;if(result.token_kind)metaTokenKind=result.token_kind;if(result.saved){toast(lang==='es'?'Clave de Meta guardada localmente. Buscando cuentas...':'Meta key saved locally. Finding accounts...');renderTokenSavedState(result.token_kind||metaTokenKind);await refreshSocialAccounts()}else{lastMetaTokenSaved='';renderSocialAccountResults({...result,accounts:[]})}}finally{metaTokenSaving=false}}
function focusGuideResults(box){setTimeout(()=>box?.scrollIntoView({behavior:'smooth',block:'center'}),90)}
function encodeAccountChoice(account){return encodeURIComponent(JSON.stringify(account||{})).replaceAll("'","%27")}
function decodeAccountChoice(value){
 try{
  if(typeof value==='object'&&value)return value;
  const raw=String(value||'');
  if(raw.trim().startsWith('{'))return JSON.parse(raw);
  if(raw.includes('%7B')||raw.includes('%22'))return JSON.parse(decodeURIComponent(raw));
  return {id:raw};
 }catch(_err){return {id:String(value||'')}}
}
function accountLimitMessage(account){
 const reason=account.limit_reason||account.reason||'';
 if(reason==='max_accounts')return lang==='es'?'Límite de 5 cuentas alcanzado':'5-account limit reached';
 if(reason==='business_manager_mismatch')return account.requires_business_replacement_confirmation?(lang==='es'?'Requiere confirmar cambio de negocio':'Business change confirmation required'):(lang==='es'?'Pertenece a otro Business Manager':'Different Business Manager');
 if(reason==='business_manager_unknown')return account.requires_business_replacement_confirmation?(lang==='es'?'Requiere confirmar cambio de negocio':'Business change confirmation required'):(lang==='es'?'Meta no confirmó el Business Manager':'Business Manager not confirmed');
 if(account.managed)return account.active?(lang==='es'?'Activa ahora':'Active now'):(lang==='es'?'Ya agregada':'Already added');
 return lang==='es'?'Disponible para agregar':'Ready to add';
}
function accountChoiceCard(account){
 const name=account.name||account.id;
 const bm=account.business_name||account.business_id||'';
 const meta=[account.id,account.currency,bm?`BM: ${bm}`:''].filter(Boolean).join(' · ');
 const canSelect=account.can_select!==false;
 const status=accountLimitMessage(account);
 // Keep the account payload in a data attribute instead of interpolating it into
 // the mini action-language. Account names/business metadata can contain quotes,
 // ampersands, or other characters that make the generated action unparsable;
 // when that happened the button rendered but silently did nothing after a key
 // change. The delegated handler reads the already parsed DOM attribute safely.
 const encodedChoice=encodeAccountChoice(account);
 const action=canSelect?`data-account-choice="${escapeHtml(encodedChoice)}" data-action-code="selectSocialAccountFromElement(event,source)"`:'disabled';
 const label=account.requires_business_replacement_confirmation?(lang==='es'?'Cambiar a esta cuenta':'Switch to this account'):(account.managed?(lang==='es'?'Usar esta cuenta y seguir':'Use this account and continue'):(lang==='es'?'Agregar esta cuenta y seguir':'Add this account and continue'));
 const warning=account.requires_business_replacement_confirmation?`<p class="notice">${lang==='es'?'Al continuar, te mostraremos una confirmación antes de limpiar la configuración del negocio anterior.':'A confirmation will appear before the previous business setup is cleared.'}</p>`:'';
 return `<article class="found-choice-card ad-account-choice"><div><span class="choice-kicker">${escapeHtml(status)}</span><b>${escapeHtml(name)}</b><p>${escapeHtml(meta)}</p>${warning}</div><button class="btn primary" type="button" ${action}>${label}</button></article>`;
}
function bindAccountChoiceButtons(box){
 box?.querySelectorAll?.('[data-account-choice]').forEach(button=>button.addEventListener('click',event=>{
  // Keep this direct listener as a resilient fallback for environments where a
  // browser extension, cached script, or an interrupted dashboard boot prevents
  // the document-level delegated listener from receiving the click.
  event.preventDefault();event.stopPropagation();
  selectSocialAccount(button.dataset.accountChoice).catch(err=>{console.error(err);toast(err.message||String(err))});
 }));
}
function renderSocialAccountResults(res){
 const box=qs('#social-account-results');if(!box)return;
 if(res.accounts&&res.accounts.length){
  const single=res.accounts.length===1;
  const managed=res.managed_ad_accounts||{};const bm=managed.business_manager||res.business_manager||{};
  const count=`${managed.used||0}/${managed.max_accounts||res.max_managed_accounts||5}`;
  const rule=lang==='es'?`Puedes agregar hasta 5 cuentas, todas bajo el mismo Business Manager${bm.name||bm.id?`: ${bm.name||bm.id}`:'.'}`:`You can add up to 5 accounts, all under the same Business Manager${bm.name||bm.id?`: ${bm.name||bm.id}`:'.'}`;
  box.innerHTML=`<div class="guide-panel found-summary"><b>${single?(lang==='es'?'Encontré tu cuenta publicitaria':'I found your ad account'):(lang==='es'?'Elige o agrega una cuenta publicitaria':'Choose or add an ad account')}</b><p>${single?(lang==='es'?'Haz clic en el botón rosa y seguimos al siguiente paso.':'Click the pink button and we continue to the next step.'):(lang==='es'?'Elige una cuenta real de este mismo negocio.':'Choose a real account from this same business.')}</p><p class="notice">${escapeHtml(rule)} · ${escapeHtml(count)}</p></div><div class="account-choice-grid">${res.accounts.map(accountChoiceCard).join('')}</div>`;
  bindAccountChoiceButtons(box);
  focusGuideResults(box);
  return;
 }
 const output=String(res.output||'').slice(0,900);
 const expired=Boolean(res.needs_login||res.token_expired||/expired|OAuthException|Code:\\s*190|auth login/i.test(output));
 if(expired){
  goToMetaTokenStep('expired',output);
  return;
 }
 const loginHint=res.message||(lang==='es'?'No pude traer cuentas todavía. La clave quedó guardada; revisa permisos de anuncios o intenta crear una clave nueva.':'I could not fetch accounts yet. The key was saved; check ad permissions or try creating a new key.');
 const detail=res.graph_checked?(lang==='es'?'Probé también con Meta Graph directo.':'I also checked directly with Meta Graph.'):'';
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No encontré cuentas publicitarias':'No ad accounts found'}</b><p>${escapeHtml(loginHint)}</p>${detail?`<p class="notice">${detail}</p>`:''}<div class="onboarding-step-actions"><button class="btn primary" type="button" data-action-code="goToMetaTokenStep()">${lang==='es'?'Pegar otra clave':'Paste another key'}</button><button class="btn" type="button" data-action-code="refreshSocialAccounts()">${lang==='es'?'Buscar otra vez':'Search again'}</button></div>${output?`<details class="helper-command"><summary>${lang==='es'?'Detalles técnicos':'Technical details'}</summary><span class="step-command">${escapeHtml(output)}</span></details>`:''}</div>`;
}
async function refreshSocialAccounts(){const box=qs('#social-account-results');if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando cuentas...':'Finding accounts...'}</p></div>`;const res=await api('/api/social/accounts');renderSocialAccountResults(res)}
function discoveryResultsBox(){return qs('#destination-discovery-results')||qs('#social-account-results')}
function encodePageChoice(page){return encodeURIComponent(JSON.stringify(page||{}))}
function renderPageChoice(page){
 const ig=page.instagram||{};const website=page.website||page.link||'';const encoded=encodePageChoice(page);
 const details=[page.id,ig.id?`Instagram: ${ig.username||ig.name||ig.id}`:'',website].filter(Boolean).join(' · ');
 return `<article class="found-choice-card destination-choice-card"><div><span class="choice-kicker">${lang==='es'?'Página encontrada':'Page found'}</span><b>${escapeHtml(page.name||page.id)}</b><p>${escapeHtml(details)}</p></div><button class="btn primary" type="button" data-action-code="selectMetaDestination('${encoded}')">${lang==='es'?'Usar esta página':'Use this Page'}</button></article>`;
}
async function selectMetaDestination(encoded){
 const page=JSON.parse(decodeURIComponent(encoded));const ig=page.instagram||{};const website=page.website||page.link||'';
 const payload={page_id:page.id||'',instagram_actor_id:ig.id||'',landing_url:website||''};
 try{await api('/api/setup-config',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Página guardada. Sigamos.':'Page saved. Let us continue.');await load();advanceOnboardingAfterLoad()}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm(payload);return}throw err}
}
function renderDiscoveredAssets(res){
 const box=discoveryResultsBox();if(!box)return;
 const result=res.result||res;const s=result.suggested||{};const pages=result.pages||[];const urls=result.urls||[];
 const suggestedPage=s.page_id?{id:s.page_id,name:s.page_name||s.page_id,instagram:s.instagram_actor_id?{id:s.instagram_actor_id,username:s.instagram_username||''}:null,website:s.landing_url||''}:null;
 const choices=pages.length?pages:(suggestedPage?[suggestedPage]:[]);
 if(result.ok&&(result.saved||choices.length)){
  if(choices.length){
   const single=choices.length===1;
   box.innerHTML=`<div class="guide-panel found-summary"><b>${single?(lang==='es'?'Encontré tu página':'I found your Page'):(lang==='es'?'Elige tu página':'Choose your Page')}</b><p>${single?(lang==='es'?'Haz clic en el botón rosa para guardar esta página y seguir.':'Click the pink button to save this Page and continue.'):(lang==='es'?'Elige la página de Facebook que usarás en tus anuncios. Si tiene Instagram conectado, también lo guardo.':'Choose the Facebook Page you will use in ads. If it has connected Instagram, I save it too.')}</p></div><div class="destination-choice-grid">${choices.map(renderPageChoice).join('')}</div>`;
   focusGuideResults(box);
   return;
  }
  const saved=[];
  if(s.instagram_actor_id)saved.push(`Instagram: ${s.instagram_username||s.instagram_actor_id}`);
  if(s.landing_url)saved.push(s.landing_url);
  box.innerHTML=`<div class="guide-panel found-summary"><b>${lang==='es'?'Datos guardados':'Details saved'}</b><p>${escapeHtml(saved.join(' · ')|| (lang==='es'?'Meta respondió correctamente.':'Meta answered correctly.'))}</p></div>`;
  focusGuideResults(box);
  return;
 }
 box.innerHTML=`<div class="guide-card"><b>${lang==='es'?'No pude encontrar todo automáticamente':'I could not find everything automatically'}</b><p>${lang==='es'?'Tu clave de Meta puede no tener permiso para ver páginas, o tu página e Instagram pueden no estar conectados. Puedes seguir y escribir esos datos en el siguiente paso.':'Your Meta key may not be allowed to see Pages, or your Page and Instagram may not be connected. You can continue and enter those details in the next step.'}</p><p class="notice">${pages.length?`${pages.length} page(s)`:''}${urls.length?` · ${urls.length} URL(s)`:''}</p></div>`;
}
async function discoverMetaAssets(id){const box=discoveryResultsBox();if(box)box.innerHTML=`<div class="guide-card"><p>${lang==='es'?'Buscando página, Instagram y web conectados...':'Finding connected Page, Instagram, and website...'}</p></div>`;const res=await api('/api/social/discover-assets',{method:'POST',body:JSON.stringify({ad_account_id:id})});renderDiscoveredAssets(res);return res}
function selectSocialAccountFromElement(event,source){
 const button=source||event?.target?.closest?.('[data-account-choice]');
 const encoded=button?.dataset?.accountChoice||'';
 if(!encoded){toast(lang==='es'?'No pude leer esta cuenta. Vuelve a buscarla.':'I could not read this account. Search for it again.');return}
 return selectSocialAccount(encoded);
}
async function selectSocialAccount(choice){const account=decodeAccountChoice(choice);const id=account.id||account.ad_account_id||'';if(!id){toast(lang==='es'?'La cuenta no tiene un ID válido. Vuelve a buscarla.':'This account has no valid ID. Search for it again.');return}const box=qs('#social-account-results');if(box)box.setAttribute('aria-busy','true');toast(lang==='es'?'Guardando esta cuenta...':'Saving this account...');const payload={ad_account_id:id,account_name:account.name||'',account_currency:account.currency||'',account_status:account.status||'',business_manager_id:account.business_id||account.business_manager_id||'',business_manager_name:account.business_name||account.business_manager_name||''};if(account.confirm_replace_business)payload.confirm_replace_business=true;try{await api('/api/social/default-account',{method:'POST',body:JSON.stringify(payload)})}catch(err){if(needsBusinessReplacement(err)){showBusinessReplacementConfirm({...payload,_meta_flow:'social_account'});return}throw err}const input=qs('input[name="ad_account_id"]');if(input)input.value=id;toast(lang==='es'?'Cuenta guardada. Buscando perfiles conectados...':'Account saved. Finding connected assets...');const discovered=await discoverMetaAssets(id);try{await api('/api/action',{method:'POST',body:JSON.stringify({action:'refresh_insights'})})}catch(err){}await load();const steps=onboardingSteps();const destinationIndex=steps.findIndex(s=>s.id==='destination');if(destinationIndex>=0){onboardingFlowTouched=true;onboardingFlowStep=destinationIndex;renderOnboardingFlow();renderDiscoveredAssets(discovered)}else advanceOnboardingAfterLoad();if(box)box.removeAttribute('aria-busy')}
async function unlockFromOnboarding(e){e.preventDefault();const input=qs('#onboarding-password');const err=qs('#onboarding-unlock-error');const value=(input?.value||'').trim();const remember=Boolean(qs('#onboarding-remember')?.checked);if(!value)return;if(err){err.textContent='';err.classList.remove('show')}try{await unlockWithPassword(value,remember)}catch(ex){if(err){err.textContent=t('unlock_failed');err.classList.add('show')}return}toast(lang==='es'?'Dashboard desbloqueado':'Dashboard unlocked');onboardingFlowStep=Math.max(onboardingFlowStep,1);await load()}
async function setDashboardPasswordFromOnboarding(e){e.preventDefault();const password=(qs('#new-dashboard-password')?.value||'').trim();const confirm=(qs('#confirm-dashboard-password')?.value||'').trim();const remember=Boolean(qs('#new-dashboard-remember')?.checked);const err=qs('#dashboard-password-error');if(err){err.textContent='';err.classList.remove('show')}if(password.length<8){if(err){err.textContent=lang==='es'?'Usa al menos 8 caracteres.':'Use at least 8 characters.';err.classList.add('show')}return}if(password!==confirm){if(err){err.textContent=lang==='es'?'Las contraseñas no coinciden.':'Passwords do not match.';err.classList.add('show')}return}const res=await fetch('/api/dashboard-password',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':dashboardPassword()},body:JSON.stringify({password,confirm_password:confirm,remember_device:remember})});if(!res.ok){if(err){err.textContent=await responseErrorMessage(res);err.classList.add('show')}return}const data=await res.json();storeDashboardSession(data.result||data,remember);toast(lang==='es'?'Contraseña guardada. Sigamos con el siguiente paso.':'Password saved. Let us continue with the next step.');await load();onboardingFlowTouched=true;advanceOnboardingAfterLoad()}
async function activateLicenseFromForm(e){
 e.preventDefault();
 const payload=Object.fromEntries(new FormData(e.target).entries());
 await activateLicense(false,payload);
}
async function activateLicense(transferDevice=false,extraPayload={}){
 const payload={...(extraPayload||{}),transfer_device:transferDevice};
 const res=await api('/api/license/activate',{method:'POST',body:JSON.stringify(payload)});
 const result=res.result||{};
 toast(`${t('toast_license')}: ${localText(result.detail||result.status||'')}`);
 await load();
 if(result&&result.valid){advanceOnboardingAfterLoad();return}
 if(result.status==='device_limit'&&result.transfer_available&&!transferDevice)showLicenseTransferConfirm(extraPayload)
}
function showLicenseTransferConfirm(extraPayload={}){const box=qs('#confirm-overlay');window.pendingLicenseActivationPayload=extraPayload||{};box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Usar licencia en este equipo':'Use license on this device'}</h2><p>${lang==='es'?'Esta licencia Individual ya esta activa en otro equipo. Si continuas, este equipo quedara como el equipo activo para nuevas validaciones y el anterior perdera acceso cuando vuelva a validar la licencia online.':'This Individual license is already active on another device. If you continue, this device becomes the active device for new validations and the previous one loses access when it validates online again.'}</p><p class="notice">${lang==='es'?'Si estas cambiando de PC o reinstalando el producto, esta es la opcion correcta.':'If you are changing PC or reinstalling the product, this is the right option.'}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Cancelar':'Cancel'}</button><button class="btn primary" type="button" data-action-code="closeConfirm();activateLicense(true,window.pendingLicenseActivationPayload||{})">${lang==='es'?'Transferir a este equipo':'Transfer to this device'}</button></div></div>`;box.classList.add('open')}
let decisionConfirmResolver=null;
function resolveDecisionConfirm(value){const resolver=decisionConfirmResolver;decisionConfirmResolver=null;qs('#confirm-overlay')?.classList.remove('open');if(resolver)resolver(Boolean(value))}
function closeConfirm(){resolveDecisionConfirm(false)}
function showDecisionConfirm(options={}){
 const box=qs('#confirm-overlay');
 const items=(options.items||[]).filter(Boolean);
 const agentDraft=String(options.agentDraft||'');
 return new Promise(resolve=>{
  decisionConfirmResolver=resolve;
  box.innerHTML=`<div class="confirm-card"><h2>${escapeHtml(options.title||'')}</h2><p>${escapeHtml(options.body||'')}</p>${items.length?`<ul>${items.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`:''}<div class="confirm-actions"><button class="btn" type="button" data-action-code="resolveDecisionConfirm(false)">${escapeHtml(options.cancelLabel||(lang==='es'?'Cancelar':'Cancel'))}</button>${agentDraft?`<button class="btn ask-btn" type="button" data-action-code="resolveDecisionConfirm(false);openChat(${chatArg(agentDraft)})">${lang==='es'?'Preguntar al manager':'Ask manager'}</button>`:''}<button class="btn primary" type="button" data-action-code="resolveDecisionConfirm(true)">${escapeHtml(options.confirmLabel||t('approve'))}</button></div></div>`;
  box.classList.add('open');
 });
}
function showOnboardingCompleteConfirm(){const box=qs('#confirm-overlay');box.innerHTML=`<div class="confirm-card"><h2>${lang==='es'?'Todo está listo':'Everything is ready'}</h2><p>${lang==='es'?'Admira IA ya tiene Meta, modelo y Telegram. ChatGPT para imágenes puede conectarse ahora o después desde Configuración.':'Admira IA now has Meta, a model, and Telegram. ChatGPT for images can be connected now or later from Setup.'}</p><div class="confirm-actions"><button class="btn" type="button" data-action-code="closeConfirm()">${lang==='es'?'Seguir revisando':'Keep reviewing'}</button><button class="btn primary" type="button" data-action-code="finishOnboardingConfirmed()">${lang==='es'?'Abrir dashboard':'Open dashboard'}</button></div></div>`;box.classList.add('open')}
async function finishOnboardingConfirmed(){closeConfirm();await finishOnboardingAndStartTour('manual')}
async function completeOnboarding(){
 const steps=onboardingSteps();
 const missingIndex=steps.findIndex(step=>step.status!=='ok');
 if(missingIndex>=0){
  const labels=lang==='es'?['la contraseña','Meta y sus dos tokens','el modelo','Telegram']:['the password','Meta and both tokens','the model','Telegram'];
  toast(`${lang==='es'?'Completa primero':'Complete first'} ${labels[missingIndex]}.`);
  qs(`#activation-${missingIndex+1}`)?.scrollIntoView({behavior:'smooth',block:'start'});
  return;
 }
 showOnboardingCompleteConfirm();
}
async function skipOnboarding(){const ok=await showDecisionConfirm({title:lang==='es'?'Completar después':'Finish later',body:lang==='es'?'Abriré el dashboard ahora. Arriba verás un aviso brillante para volver y terminar lo pendiente cuando quieras.':'I will open the dashboard now. A glowing notice at the top will bring you back to finish the pending parts later.',confirmLabel:lang==='es'?'Abrir dashboard':'Open dashboard'});if(!ok)return;await api('/api/onboarding/skip',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Puedes completar la configuración después.':'You can finish setup later.');await load()}
async function resumeOnboarding(){await api('/api/onboarding/reset',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Sigamos con lo pendiente.':'Let us finish the pending setup.');await load()}
async function resetOnboarding(){const ok=await showDecisionConfirm({title:lang==='es'?'Revisar configuración inicial':'Run initial setup again',body:lang==='es'?'La guía inicial volverá a aparecer para revisar conexión, cuenta, página y reglas. No borra tus datos por sí sola.':'The initial guide will appear again to review connection, account, Page, and rules. It does not delete your data by itself.',confirmLabel:lang==='es'?'Abrir guía inicial':'Open initial guide',agentDraft:lang==='es'?'Ayúdame a revisar si necesito repetir la configuración inicial o solo cambiar una parte.':'Help me decide whether I should rerun initial setup or only change one setup area.'});if(!ok)return;await api('/api/onboarding/reset',{method:'POST',body:JSON.stringify({})});toast(lang==='es'?'Guía inicial abierta':'Initial guide opened');await load()}
qs('#unlock-form').addEventListener('submit',async e=>{e.preventDefault();const value=qs('#unlock-password').value.trim();const remember=Boolean(qs('#remember-device')?.checked);if(!value)return;setUnlockError('');if(unlockMode==='create'){const confirm=(qs('#unlock-confirm-password')?.value||'').trim();if(value.length<8){setUnlockError(t('dashboard_password_short'));return}if(value!==confirm){setUnlockError(t('dashboard_password_mismatch'));return}const res=await fetch('/api/dashboard-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:value,confirm_password:confirm,remember_device:remember})});if(!res.ok){setUnlockError(await responseErrorMessage(res));return}const data=await res.json();const session=storeDashboardSession(data.result||data,remember);hideUnlock();if(unlockResolver){unlockResolver(session);unlockResolver=null}qs('#unlock-password').value='';qs('#unlock-confirm-password').value='';toast(lang==='es'?'Contraseña creada. Seguimos con la configuración.':'Password created. Continuing setup.');await load();return}try{const session=await unlockWithPassword(value,remember);hideUnlock();if(unlockResolver){unlockResolver(session);unlockResolver=null}qs('#unlock-password').value=''}catch(err){setUnlockError(t('unlock_failed'))}})
qs('#language-select').addEventListener('change',e=>{lang=e.target.value;localStorage.setItem('dashboardLang',lang);render()})
qs('#chat-input').addEventListener('input',resizeChatInput)
qs('#agent-bar-input').addEventListener('input',resizeAgentBarInput)
qs('#chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const form=qs('#chat-form');if(form.requestSubmit){form.requestSubmit()}else{form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}}})
qs('#agent-bar-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const form=qs('#agent-chat-bar');if(form.requestSubmit){form.requestSubmit()}else{form.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))}}})
qs('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const input=qs('#chat-input');const text=input.value.trim();if(!text)return;input.value='';resizeChatInput();await sendChatMessage(text)})
qs('#agent-chat-bar').addEventListener('submit',async e=>{e.preventDefault();const input=qs('#agent-bar-input');const text=input.value.trim();if(!text){input.focus();return}input.value='';resizeAgentBarInput();await sendChatMessage(text,{workspace:true})})
function activateDashboardTab(name){const target=String(name||'overview');document.querySelectorAll('.tab').forEach(btn=>btn.classList.toggle('active',btn.dataset.tab===target));['overview','setup','creator','audiences','creatives','reports'].forEach(tab=>qs('#tab-'+tab)?.classList.toggle('hidden',tab!==target))}
function openModelReconnectFromUrl(){if(urlParams.get('reconnect_model')!=='1')return;activateDashboardTab('setup');setTimeout(()=>{const card=qs('#chatgpt-panel .chatgpt-connect-card');if(!card)return;card.classList.add('recovery-focus');card.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>card.classList.remove('recovery-focus'),5000)},180);urlParams.delete('reconnect_model');const next=urlParams.toString();history.replaceState({},'',window.location.pathname+(next?'?'+next:'')+window.location.hash)}
async function openUpdateFromUrl(){if(urlParams.get('open_update')!=='1')return;const requestedVersion=String(urlParams.get('update_version')||'').trim();activateDashboardTab('setup');urlParams.delete('open_update');urlParams.delete('update_version');const next=urlParams.toString();history.replaceState({},'',window.location.pathname+(next?'?'+next:'')+window.location.hash);setTimeout(()=>qs('#update-rollback-panel')?.scrollIntoView({behavior:'smooth',block:'center'}),180);const checked=await checkForUpdates(true,{silent:true});if(checked?.available){showUpdateDetails();return}if(updateCheckError){toast(updateCheckError);return}const installed=String(checked?.current_version||'').trim();if(requestedVersion&&installed===requestedVersion){toast(lang==='es'?`La actualización ${requestedVersion} ya está instalada.`:`Update ${requestedVersion} is already installed.`);return}toast(lang==='es'?'Esta notificación ya no está pendiente; el producto está actualizado.':'This notification is no longer pending; the product is up to date.')}
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>activateDashboardTab(btn.dataset.tab)))
qs('#campaign-form').addEventListener('submit',async e=>{e.preventDefault();syncTargetingHidden('location');syncTargetingHidden('interest');const payload=Object.fromEntries(new FormData(e.target).entries());await api('/api/campaigns',{method:'POST',body:JSON.stringify(payload)});toast(lang==='es'?'Campaña enviada para tu aprobación':'Campaign sent for your approval');await load()})
qs('#audience-form').addEventListener('submit',async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.target).entries());payload.consent=e.target.elements.consent.checked?'yes':'no';await buildAudienceStrategy(payload)})
installDelegatedActions();
applyTranslations();
applyDashboardTheme();
syncDashboardView();
syncPanels();
load();
