// O navegador usa a API do Flask para consultar e salvar os dados.

// Atalhos para localizar um elemento ou uma lista de elementos na página.
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

// Formata valores em reais no padrão brasileiro.
const currency = n => new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL'
}).format(n);

// Escapa textos cadastrados para que sejam exibidos como texto, sem executar HTML.
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
} [c]));

// Monta a data local sem mudanças causadas pela conversão de fuso horário.
const localDate = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
};

// Identifica a página atual e mantém em memória os dados já carregados.
const section = document.body.dataset.section;
let transactions = [],
  goals = [],
  charts = {},
  activePlan = 'premium',
  toastTimer;
const colors = ['#219c7e', '#8cabc1', '#d5b580', '#9eacd4', '#aacba7', '#dbacaa', '#b8a3ca'];

// Salva preferências do navegador; receitas, despesas e metas ficam no SQLite.
const storage = {
  get(k, fallback) {
    try {
      return localStorage.getItem(k) || fallback;
    } catch {
      return fallback;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch {}
  }
};

// Exibe uma mensagem temporária de confirmação ou erro.
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 5500);
}

// Centraliza as chamadas ao Flask e transforma erros em mensagens para a tela.
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {
    method,
    headers: body ? {
      'Content-Type': 'application/json'
    } : {},
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Não foi possível concluir a operação.');
  return data;
}

// Gráficos SVG locais: funcionam sem CDN e apresentam os valores no próprio gráfico.
function chart(id, type, data, extra = {}) {
  const host = document.getElementById(id);
  if (!host) return;
  charts[id] = {type, data, extra};
  const styles = getComputedStyle(document.body);
  const muted = styles.getPropertyValue('--muted').trim();
  const line = styles.getPropertyValue('--line').trim();
  const text = styles.getPropertyValue('--text').trim();
  const green = styles.getPropertyValue('--green').trim();
  const w = 620, h = 245;
  let svg = '';
  const label = value => escapeHTML(String(value));
  if (type === 'doughnut') {
    const values = data.datasets[0].data;
    const sum = values.reduce((a, b) => a + b, 0);
    let offset = 0;
    svg = values.map((v, i) => {
      const pct = sum ? v / sum * 100 : 0;
      const circle = `<circle cx="170" cy="115" r="77" fill="none" stroke="${data.datasets[0].backgroundColor[i]}" stroke-width="22" pathLength="100" stroke-dasharray="${Math.max(0,pct-.8)} ${100-Math.max(0,pct-.8)}" stroke-dashoffset="${-offset}" transform="rotate(-90 170 115)"><title>${label(data.labels[i])}: ${currency(v)}</title></circle>`;
      offset += pct;
      return circle;
    }).join('');
    svg += `<text x="170" y="109" text-anchor="middle" fill="${muted}" font-size="12">Despesas do mês</text><text x="170" y="137" text-anchor="middle" fill="${text}" font-size="24" font-weight="600">${currency(sum)}</text>`;
    host.innerHTML = `<svg viewBox="0 0 340 230" role="img" aria-label="${label(data.labels.map((l,i)=>l+': '+currency(values[i])).join('; '))}">${svg}</svg>`;
    return;
  }
  const sets = data.datasets;
  const values = sets.flatMap(d => d.data);
  const maximum = Math.max(1, ...values);
  const max = maximum === 1 ? 1 : maximum * 1.14;
  const left = 66, top = 8, bottom = 213, width = w-left-12, height = bottom-top;
  const y = v => bottom - Number(v)/max*height;
  for (let i = 0; i <= 4; i++) {
    const value = max*i/4;
    const position = y(value);
    const formatted = value >= 1000000 ? (value/1000000).toLocaleString('pt-BR',{maximumFractionDigits:1})+' mi' : value >= 1000 ? (value/1000).toLocaleString('pt-BR',{maximumFractionDigits:1})+' mil' : value.toLocaleString('pt-BR',{maximumFractionDigits:maximum<10?1:0});
    svg += `<line x1="${left}" x2="${w-6}" y1="${position}" y2="${position}" stroke="${line}" stroke-dasharray="3 5"/><text x="${left-10}" y="${position+4}" text-anchor="end" fill="${muted}" font-size="10">R$ ${formatted}</text>`;
  }
  if (type === 'bar') {
    const group = width/data.labels.length;
    data.labels.forEach((name, i) => {
      const center = left + group*(i+.5);
      svg += `<text x="${center}" y="238" text-anchor="middle" fill="${muted}" font-size="11">${label(name)}</text>`;
      sets.forEach((set, j) => {
        const value = set.data[i];
        const bh = Number(value)/max*height;
        svg += `<rect x="${center+(j-.5)*20-8}" y="${y(value)}" width="16" height="${bh}" rx="4" fill="${j===0?green:'#b6c3a9'}"><title>${label(name+' · '+set.label)}: ${currency(value)}</title></rect>`;
      });
    });
  } else {
    const set = sets[0];
    const n = Math.max(1,set.data.length-1);
    const points = set.data.map((v,i)=>`${left+i/n*width},${y(v)}`).join(' ');
    svg += `<polygon points="${left},${bottom} ${points} ${left+width},${bottom}" fill="${green}" opacity=".07"/><polyline points="${points}" fill="none" stroke="${green}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
    set.data.forEach((v,i)=>{
      const x=left+i/n*width;
      svg += `<circle cx="${x}" cy="${y(v)}" r="${set.data.length>60?1.8:3}" fill="${green}"><title>${label(data.labels[i])}: ${currency(v)}</title></circle>`;
      if (i===0||i===n||i===Math.round(n/2)) svg += `<text x="${x}" y="238" text-anchor="middle" fill="${muted}" font-size="10">${label(data.labels[i])}</text>`;
    });
  }
  const description = data.labels.map((name,i)=>name+': '+sets.map(d=>d.label+' '+currency(d.data[i])).join(', ')).join('; ');
  host.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${label(description)}">${svg}</svg>`;
}

// Aplica os filtros e monta a tabela de movimentações.
function drawTransactions() {
  const query = $('#search').value.toLocaleLowerCase('pt-BR');
  const category = $('#category-filter').value,
    type = $('#type-filter').value;
  let filtered = transactions.filter(t => t.description.toLocaleLowerCase('pt-BR').includes(
    query) && (!category || t.category === category) && (!type || t.type === type));
  const total = filtered.length;
  if (section === 'dashboard') filtered = filtered.slice(0, 5);
  $('#transactions').innerHTML = filtered.map(t =>
    `<tr><td><span class="transaction-icon">${t.type==='receita'?'↙':'↗'}</span>${escapeHTML(t.description)}</td><td><span class="category-tag">${escapeHTML(t.category)}</span></td><td>${new Date(t.date+'T12:00:00').toLocaleDateString('pt-BR')}</td><td class="${t.type==='receita'?'green-text':''}">${t.type==='receita'?'+':'−'} ${currency(t.amount)}</td><td><div class="row-actions"><button data-edit-transaction="${t.id}" aria-label="Editar ${escapeHTML(t.description)}">Editar</button><button data-delete-transaction="${t.id}" aria-label="Excluir ${escapeHTML(t.description)}">Excluir</button></div></td></tr>`
    ).join('') || '<tr><td colspan="5" class="empty">Nenhuma movimentação encontrada.</td></tr>';
  $('#table-count').textContent = `${filtered.length} de ${total} movimentações`;
}

// Monta os cartões com o progresso e o valor mensal de cada meta.
function drawGoals() {
  $('#goals').innerHTML = goals.map((g, i) => {
    const percent = Math.min(100, g.saved / g.target * 100);
    return `<article class="goal-card"><div class="goal-top"><span class="goal-symbol">${['◎','✈','▱'][i%3]}</span><div class="goal-actions"><button data-edit-goal="${g.id}" aria-label="Editar ${escapeHTML(g.name)}">Editar</button><button data-delete-goal="${g.id}" aria-label="Excluir ${escapeHTML(g.name)}">Excluir</button></div></div><h3>${escapeHTML(g.name)}</h3><div class="goal-amount"><strong>${currency(g.saved)}</strong> de ${currency(g.target)}</div><div class="progress" role="progressbar" aria-label="${escapeHTML(g.name)}" aria-valuenow="${percent.toFixed(0)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${percent}%"></span></div><div class="goal-foot"><b>${percent.toFixed(0)}% do caminho</b><span>Até ${new Date(g.deadline+'T12:00:00').toLocaleDateString('pt-BR',{month:'short',year:'numeric'})}</span></div><p class="goal-monthly">${g.saved>=g.target?'Você chegou lá! Meta concluída.':`Próximo passo: guardar ${currency(g.monthly)}/mês`}</p></article>`;
  }).join('') || '<div class="empty-state"><span class="goal-symbol">◎</span><div><strong>Seu próximo sonho começa aqui.</strong><p>Defina um objetivo e acompanhe cada conquista.</p></div><button class="text-button" id="empty-goal">Criar minha primeira meta ↗</button></div>';
}

// Busca os dados atuais e atualiza totais, tabelas, metas e gráficos.
async function refresh() {
  const [summary, items, targets] = await Promise.all([api('/api/resumo'), api('/api/transacoes'),
    api('/api/metas')
  ]);
  transactions = items;
  goals = targets;
  activePlan = summary.plan;
  for (const key of ['balance', 'income', 'expense']) $('#' + key).textContent = currency(summary[
    key]);
  $('#plan-badge').textContent = 'MoneyWise ' + activePlan[0].toUpperCase() + activePlan.slice(1);
  $$('.choose-plan').forEach(b => {
    b.disabled = b.dataset.plan === activePlan;
    b.textContent = b.disabled ? '✓ Plano ativo' : 'Experimentar ' + b.dataset.plan[0]
      .toUpperCase() + b.dataset.plan.slice(1);
  });
  drawTransactions();
  drawGoals();
  const ratio = summary.income > 0 ? summary.expense / summary.income * 100 : null;
  $('#saving-rate').textContent = ratio === null ? 'Sem receitas' : ratio.toLocaleString('pt-BR', {maximumFractionDigits:0}) + '%';
  $('#month-progress').style.width = (ratio === null ? 0 : Math.min(100, ratio)) + '%';
  $('#month-insight').textContent = summary.income === 0 && summary.expense === 0
    ? 'Registre sua primeira movimentação para enxergar seu mês com mais clareza.'
    : summary.income === 0 ? 'Você já tem despesas registradas. Adicione suas receitas para comparar entradas e saídas.'
    : summary.expense > summary.income ? 'As despesas deste mês passaram das receitas. Revise suas categorias para planejar o próximo passo.'
    : 'Neste mês, suas receitas superam ou igualam as despesas. Acompanhe de perto para manter seu planejamento.';
  if (section === 'dashboard') chart('cash-chart', 'bar', {
    labels: summary.series.map(s => new Date(s.month + '-01T12:00:00').toLocaleDateString(
      'pt-BR', {
        month: 'short'
      })),
    datasets: [{
      label: 'Receitas',
      data: summary.series.map(s => s.income),
      backgroundColor: '#279e80',
      borderRadius: 5,
      barPercentage: .65,
      categoryPercentage: .55
    }, {
      label: 'Despesas',
      data: summary.series.map(s => s.expense),
      backgroundColor: '#c0d1d4',
      borderRadius: 5,
      barPercentage: .65,
      categoryPercentage: .55
    }]
  });
  if (['dashboard', 'relatorios', 'assistente'].includes(section)) {
    if (activePlan === 'free') {
      $('#report-lock').textContent =
        'Relatórios disponíveis no Plus e Premium. Experimente na página Planos.';
      $('#category-list').innerHTML = '';
      $('.donut-wrap').hidden = true;
    } else {
      const report = await api('/api/relatorios');
      $('#report-lock').textContent = report.length ? '' : 'Sem despesas neste mês.';
      $('.donut-wrap').hidden = !report.length;
      $('#category-list').innerHTML = report.map((r, i) =>
        `<div class="category-row"><span><i style="background:${colors[i%colors.length]}"></i>${escapeHTML(r.category)}</span><b>${currency(r.total)}</b></div>`
        ).join('');
      if (report.length) chart('category-chart', 'doughnut', {
        labels: report.map(r => r.category),
        datasets: [{
          data: report.map(r => r.total),
          backgroundColor: report.map((_, i) => colors[i % colors.length]),
          borderWidth: 0,
          spacing: 4,
          borderRadius: 4
        }]
      });
    }
    chatControls();
    $('#chat-input').placeholder = 'O que você quer entender?';
  }
}

// Preenche a janela de cadastro para criar ou editar um registro.
function openForm(kind, item) {
  const form = $('#' + kind + '-form');
  form.reset();
  form.elements.id.value = '';
  if (item)
    for (const [key, value] of Object.entries(item)) {
      if (form.elements[key]) form.elements[key].value = value;
    } else if (kind === 'transaction') form.elements.date.value = localDate();
    else {
      form.elements.saved.value = 0;
      form.elements.deadline.min = localDate();
    } if (kind === 'transaction') $('#transaction-title').textContent = item ? 'Editar lançamento' :
    'Novo lançamento';
  $('#' + kind + '-dialog').showModal();
}

// Envia o formulário à API e atualiza a tela após salvar.
function bindForm(kind, endpoint) {
  $('#' + kind + '-form').addEventListener('submit', async e => {
    e.preventDefault();
    const button = e.target.querySelector('button[type="submit"],button.primary');
    button.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(e.target));
      await api(endpoint + (data.id ? '/' + data.id : ''), data.id ? 'PUT' : 'POST', data);
      $('#' + kind + '-dialog').close();
      await refresh();
      toast('Salvo. Mais um passo no seu controle.');
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
  });
}
// A conversa fica apenas na memória desta aba. Nenhuma mensagem vai ao localStorage.
let chatBusy = false, chatHistory = [], chatController = null, lastQuestion = '';
let userStopped = false;

function chatControls() {
  $('#chat-input').disabled = chatBusy;
  $('#chat-form button[type="submit"]').disabled = chatBusy;
  $('#chat-form button[type="submit"]').hidden = chatBusy;
  $('#chat-stop').hidden = !chatBusy;
  $$('.suggestions button').forEach(button => button.disabled = chatBusy);
  $('#chat-context').disabled = chatBusy;
  $('#chat-clear').disabled = chatBusy;
  $('#chat-retry').disabled = chatBusy;
  $('#chat-log').setAttribute('aria-busy', String(chatBusy));
}

async function checkAI() {
  const button = $('#ai-check');
  button.disabled = true;
  try {
    const status = await api('/api/ia-status');
    $('#ai-health').textContent = (status.ready ? '● ' : '○ ') + status.message;
    $('#ai-health').classList.toggle('ready', status.ready);
  } catch {
    $('#ai-health').textContent = 'Não foi possível verificar a conexão. Tente novamente.';
    $('#ai-health').classList.remove('ready');
  } finally { button.disabled = false; }
}

async function sendMessage(message) {
  message = message.trim();
  if (chatBusy || !message) return;
  const log = $('#chat-log');
  const user = document.createElement('p');
  user.className = 'chat-message user';
  user.textContent = message;
  log.append(user);
  const responseMessage = document.createElement('p');
  responseMessage.className = 'chat-message pending';
  responseMessage.textContent = 'Preparando sua resposta…';
  log.append(responseMessage);
  log.scrollTop = log.scrollHeight;
  chatBusy = true;
  userStopped = false;
  lastQuestion = message;
  chatControls();
  $('#chat-retry').hidden = true;
  $('#chat-input').value = '';
  $('#chat-status').textContent = 'Consultando seus registros e preparando a resposta…';
  chatController = new AbortController();
  const timeout = setTimeout(() => chatController?.abort(), 160000);
  const slow = setTimeout(() => { if(chatBusy) $('#chat-status').textContent = 'O modelo pode estar carregando. A primeira resposta costuma levar mais tempo…'; }, 12000);
  let answer = '', source = 'ia', done = false;
  const textNode = document.createTextNode('');
  const sourceLabel = document.createElement('span');
  sourceLabel.className = 'message-source';
  const consume = event => {
    if(event.type === 'error') throw new Error(event.error || 'A IA não conseguiu responder.');
    if(event.type === 'source') source = event.source;
    if(event.type === 'done') done = true;
    if(event.type === 'token') {
      if(typeof event.text !== 'string') throw new Error('Resposta inválida. Tente novamente.');
      if(!answer) {
        responseMessage.replaceChildren(sourceLabel, textNode);
        responseMessage.classList.remove('pending');
        sourceLabel.textContent = source === 'registros' ? 'SEUS REGISTROS · VALORES CALCULADOS' : 'MONEYWISE · IA LOCAL';
      }
      answer += event.text;
      textNode.textContent = answer;
      $('#chat-status').textContent = source === 'registros' ? 'Conferindo seus registros…' : 'IA local está respondendo…';
      log.scrollTop = log.scrollHeight;
    }
  };
  try {
    const response = await fetch('/api/ia-chat', {
      method: 'POST', headers: {'Content-Type':'application/json'}, signal:chatController.signal,
      body: JSON.stringify({message, history:chatHistory, include_financial_context:$('#chat-context').checked, stream:true})
    });
    if(!response.ok) { const error=await response.json(); throw new Error(error.error || 'Não foi possível responder agora.'); }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while(true) {
      const part = await reader.read();
      buffer += decoder.decode(part.value || new Uint8Array(), {stream:!part.done});
      let cut;
      while((cut = buffer.indexOf('\n')) !== -1) {
        const row=buffer.slice(0,cut).trim(); buffer=buffer.slice(cut+1);
        if(row) consume(JSON.parse(row));
      }
      if(part.done) break;
    }
    if(buffer.trim()) consume(JSON.parse(buffer));
    if(!done || !answer.trim()) throw new Error('A resposta foi interrompida. Tente novamente.');
    chatHistory.push({role:'user',text:message},{role:'model',text:answer});
    chatHistory=chatHistory.slice(-4);
  } catch(error) {
    // Respostas parciais nunca entram no histórico usado nas próximas perguntas.
    const notice = error.name === 'AbortError' ? (userStopped ? 'Resposta interrompida por você.' : 'A resposta demorou. Tente novamente.') : (error instanceof TypeError ? 'Não foi possível conectar ao MoneyWise. Verifique se o sistema está aberto.' : error.message);
    responseMessage.classList.remove('pending');
    responseMessage.classList.add('chat-error');
    if(answer) responseMessage.append(document.createTextNode('\n\n' + notice));
    else responseMessage.textContent=notice;
    $('#chat-retry').hidden=false;
    $('#chat-input').value=message;
  } finally {
    clearTimeout(timeout); clearTimeout(slow);
    chatController=null; chatBusy=false;
    $('#chat-status').textContent=''; chatControls(); $('#chat-input').focus();
    log.scrollTop=log.scrollHeight;
  }
}

$('#chat-stop').onclick = () => { userStopped=true; chatController?.abort(); };
$('#chat-retry').onclick = () => sendMessage(lastQuestion);
$('#ai-check').onclick = checkAI;
$('#chat-clear').onclick = () => {
  chatHistory=[]; lastQuestion=''; $('#chat-retry').hidden=true; $('#chat-input').value='';
  const welcome=document.createElement('p'); welcome.className='chat-message';
  welcome.textContent='Nova conversa. Qual é o seu próximo passo?'; $('#chat-log').replaceChildren(welcome);
};
$('#chat-context').onchange = () => $('#chat-clear').click();

// Define o título e a descrição de cada página do sistema.
const titles = {
  dashboard: ['Seu dinheiro, com mais clareza.',
    'Cada escolha de hoje aproxima você de onde quer chegar.', 'Visão geral'
  ],
  transacoes: ['Cada movimento conta.', 'Organize entradas e saídas, sem perder os detalhes.',
    'Transações'
  ],
  metas: ['Dê espaço aos seus sonhos.', 'Transforme seus objetivos em pequenos passos possíveis.',
    'Minhas metas'
  ],
  assistente: ['Um aliado para o seu próximo passo.', 'Converse sobre suas finanças, no seu ritmo e com seus dados.', 'Assistente IA'],
  relatorios: ['Clareza para escolher melhor.',
    'Entenda seus hábitos e encontre novas possibilidades.', 'Relatórios'
  ],
  simulador: ['Um pouco hoje. Mais amanhã.', 'Descubra como o tempo pode trabalhar com você.',
    'Simulador'
  ],
  planos: ['Um plano para o seu momento.',
    'Escolha as ferramentas para construir seu próximo capítulo.', 'Planos'
  ]
};

// Mostra os blocos da página atual e aplica o tema salvo.
$$('[data-view]').forEach(e => e.hidden = !e.dataset.view.split(' ').includes(section));
$('#page-title').textContent = titles[section][0];
$('#page-subtitle').textContent = titles[section][1];
$('#breadcrumb').textContent = titles[section][2];
document.title = titles[section][2] + ' · MoneyWise';
$('#today-label').textContent = new Date().toLocaleDateString('pt-BR', {day:'numeric', month:'long', year:'numeric'});
document.body.classList.toggle('dark', storage.get('moneywise-theme', 'light') === 'dark');
document.documentElement.classList.remove('dark-start');
$('#theme').onclick = () => {
  document.body.classList.toggle('dark');
  storage.set('moneywise-theme', document.body.classList.contains('dark') ? 'dark' : 'light');
  if(charts['simulation-chart']) { const c=charts['simulation-chart']; chart('simulation-chart',c.type,c.data,c.extra); }
  refresh().catch(e => toast(e.message));
};

// Liga botões e filtros às ações de cadastro e pesquisa.
$$('.new-transaction').forEach(b => b.onclick = () => openForm('transaction'));
$('#new-goal').onclick = () => openForm('goal');
$$('[data-close]').forEach(b => b.onclick = () => $('#' + b.dataset.close).close());
['search', 'category-filter', 'type-filter'].forEach(id => $('#' + id).addEventListener(id ===
  'search' ? 'input' : 'change', drawTransactions));
bindForm('transaction', '/api/transacoes');
bindForm('goal', '/api/metas');

// Trata edição, exclusão, escolha de plano e sugestões de perguntas.
document.addEventListener('click', async e => {
  const button = e.target.closest('button');
  if (!button) return;
  try {
    for (const kind of ['transaction', 'goal']) {
      const suffix = kind[0].toUpperCase() + kind.slice(1);
      const edit = button.dataset['edit' + suffix],
        remove = button.dataset['delete' + suffix];
      const items = kind === 'transaction' ? transactions : goals;
      if (edit) openForm(kind, items.find(i => i.id === Number(edit)));
      if (remove && confirm('Excluir este registro? Esta ação não pode ser desfeita.')) {
        await api((kind === 'transaction' ? '/api/transacoes/' : '/api/metas/') + remove,
          'DELETE');
        await refresh();
        toast('Registro excluído.');
      }
    }
    if (button.dataset.plan) {
      button.disabled = true;
      await api('/api/plano', 'POST', {
        plan: button.dataset.plan
      });
      await refresh();
      toast('Plano de demonstração atualizado. Nenhuma cobrança realizada.');
    }
    if (button.id === 'empty-goal') openForm('goal');
    if (button.dataset.question) await sendMessage(button.dataset.question);
  } catch (error) {
    button.disabled = false;
    toast(error.message);
  }
});

// Cria uma categoria e atualiza as opções do formulário e do filtro.
$('#add-category').onclick = async () => {
  const name = prompt('Nome da nova categoria:');
  if (!name) return;
  try {
    const list = await api('/api/categorias', 'POST', {
      name
    });
    const selected = $('#transaction-form').elements.category;
    selected.replaceChildren(...list.map(n => new Option(n, n)));
    selected.value = name.trim();
    const filter = $('#category-filter');
    filter.replaceChildren(new Option('Todas as categorias', ''), ...list.map(n => new Option(n,
      n)));
    toast('Categoria criada.');
  } catch (error) {
    toast(error.message);
  }
};

// Envia a pergunta sem recarregar a página.
$('#chat-form').onsubmit = e => {
  e.preventDefault();
  const text = $('#chat-input').value.trim();
  if (text) sendMessage(text);
};

// Consulta a projeção financeira e desenha a evolução do saldo.
$('#simulation-form').onsubmit = async e => {
  e.preventDefault();
  const button = e.target.querySelector('button');
  button.disabled = true;
  try {
    const result = await api('/api/simulador', 'POST', Object.fromEntries(new FormData(e
      .target)));
    $('#simulation-total').textContent = currency(result.total);
    $('#simulation-details').textContent =
      `Total guardado: ${currency(result.invested)} · Rendimentos: ${currency(result.interest)}`;
    chart('simulation-chart', 'line', {
      labels: result.points.map((_, i) => i + 'm'),
      datasets: [{
        label: 'Patrimônio projetado',
        data: result.points,
        borderColor: '#199c7b',
        backgroundColor: '#199c7b15',
        fill: true,
        tension: .3,
        pointRadius: result.points.length > 24 ? 0 : 3
      }]
    });
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
};

// Lista os sete passos do desafio e recupera o progresso salvo neste navegador.
const challenges = ['Anote todas as suas fontes de renda.', 'Liste suas despesas fixas.',
  'Registre os pequenos gastos do dia.', 'Identifique uma compra que pode esperar.',
  'Escolha uma meta que faz sentido para você.', 'Planeje quanto consegue guardar por mês.',
  'Revise a semana e celebre seu primeiro passo.'
];
let completed;
try {
  completed = JSON.parse(storage.get('moneywise-challenge-personal-v1', '[]'));
  if (!Array.isArray(completed)) completed = [];
} catch {
  completed = [];
}

// Monta as caixas do desafio e salva as etapas concluídas.
$('#challenge-days').innerHTML = challenges.map((text, i) =>
  `<label><input type="checkbox" data-day="${i}" ${completed.includes(i)?'checked':''}><span>Dia ${i+1} — ${text}</span></label>`
  ).join('');
$('#challenge-start').onclick = () => $('#challenge-dialog').showModal();
$('#challenge-days').onchange = () => storage.set('moneywise-challenge-personal-v1', JSON.stringify(
  $$('#challenge-days input:checked').map(e => Number(e.dataset.day))));

// Carrega os dados quando a página abre e avisa se houver falha.
refresh().catch(error => toast('Não foi possível carregar os dados: ' + error.message));
if(['dashboard','relatorios','assistente'].includes(section)) checkAI();

// Usa o mesmo controle de tema no menu para telas menores.
document.querySelector('#mobile-theme').onclick = () => document.querySelector('#theme').click();
