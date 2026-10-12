import * as THREE from 'three';
import './style.css';

const state = {
  environment: 'dev',
  environments: [],
  overview: null,
  cost: null,
  report: null,
  activeSection: 'overview',
};

const serviceRoles = {
  'docs-assistant': 'Runbook search · RAG',
  'model-serving': 'Deployment risk model',
  'llm-gateway': 'Model routing · cost',
  'aiops-agent': 'Incident detection',
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

async function api(path, options = {}) {
  const isOperationsRequest = path.startsWith('/api/containers') || path.startsWith('/api/logs/');
  const opsToken = isOperationsRequest ? sessionStorage.getItem('forge-ops-token') : '';
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(opsToken ? { Authorization: `Bearer ${opsToken}` } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function envQuery() {
  return `environment=${encodeURIComponent(state.environment)}`;
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('visible');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('visible'), 3200);
}

function setApiState(online) {
  $('#api-state').textContent = online ? 'Connected' : 'Unavailable';
  $('#api-state').classList.toggle('is-offline', !online);
  $('.side-system .pulse-dot').classList.toggle('is-offline', !online);
}

function renderEnvironmentTabs() {
  const configured = new Set(state.environments.filter((item) => item.configured).map((item) => item.name));
  $$('.env-tab').forEach((button) => {
    const selected = button.dataset.env === state.environment;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-selected', String(selected));
    button.classList.toggle('not-configured', !configured.has(button.dataset.env));
  });
  const current = state.environments.find((item) => item.name === state.environment);
  const label = current?.label || state.environment;
  $('#breadcrumb-env').textContent = label;
  $('#intro-env-label').textContent = `${label.toUpperCase()} ENVIRONMENT`;
  $('#env-detail').textContent = current?.configured
    ? `Connected profile · live service checks enabled`
    : `Not connected · configure this environment in IDP_ENVIRONMENTS`;
  $('#env-connection-note').textContent = current?.configured ? 'LIVE SERVICE CHECKS' : 'PROFILE NOT CONFIGURED';
}

function renderServices(overview) {
  const list = $('#service-list');
  if (!overview) {
    list.innerHTML = '<div class="table-empty">No live health snapshot is available.</div>';
    $('#healthy-count').textContent = '--';
    $('#service-total').textContent = '/ --';
    $('#health-caption').textContent = 'Environment is not connected';
    return;
  }
  list.innerHTML = overview.services.map((service) => {
    const label = service.status === 'healthy' ? 'Healthy' : service.status === 'offline' ? 'Offline' : 'Unconfigured';
    const latency = service.latency_ms == null ? '—' : `${service.latency_ms} ms`;
    return `<div class="service-row">
      <span class="service-name"><i class="service-mark ${service.status}"></i><b>${escapeHTML(service.name)}</b></span>
      <span><span class="status-pill ${service.status}">${label}</span></span>
      <span class="mono latency-cell">${latency}</span>
      <span class="service-role">${escapeHTML(serviceRoles[service.name] || 'Platform service')}</span>
      <span class="endpoint-cell mono">/healthz</span>
    </div>`;
  }).join('');
  $('#healthy-count').textContent = String(overview.healthy).padStart(2, '0');
  $('#service-total').textContent = `/ ${String(overview.total).padStart(2, '0')}`;
  $('#health-caption').textContent = overview.healthy === overview.total
    ? 'All configured APIs responded'
    : `${overview.total - overview.healthy} service(s) need attention`;
  $('#intro-updated').textContent = new Date(overview.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  $('#last-refresh').textContent = `Checked ${new Date(overview.checked_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  $('#live-state').classList.toggle('has-issues', overview.healthy < overview.total);
}

async function refreshOverview() {
  try {
    state.overview = await api(`/api/overview?${envQuery()}`);
    setApiState(true);
    renderServices(state.overview);
    const url = state.overview.grafana_url;
    const dashboard = $('#mission-link');
    dashboard.href = url || '#';
    dashboard.hidden = !url;
  } catch (error) {
    state.overview = null;
    setApiState(error.message !== 'Environment is not configured');
    renderServices(null);
    $('#last-refresh').textContent = error.message;
  }
}

async function refreshIncidents() {
  try {
    const data = await api(`/api/incidents?${envQuery()}`);
    const incidents = data.incidents || [];
    $('#incident-count').textContent = String(incidents.length).padStart(2, '0');
    $('#incident-list').innerHTML = incidents.length ? incidents.slice(0, 5).map((incident) => `
      <article class="incident-item">
        <span class="incident-state ${incident.action === 'restarted' ? 'actioned' : ''}"><i></i>${escapeHTML(incident.action || 'recorded')}</span>
        <span class="incident-service">${escapeHTML(incident.service || 'service')}</span>
        <span class="incident-rule">${escapeHTML(incident.rule || 'event')}</span>
        <span class="incident-summary">${escapeHTML(incident.summary || '')}</span>
        <time>${escapeHTML(incident.time || '')}</time>
      </article>`).join('') : '<div class="incident-empty">No incidents recorded for this environment.</div>';
  } catch {
    $('#incident-count').textContent = '--';
    $('#incident-list').innerHTML = '<div class="incident-empty">Incident service is unavailable or this environment is not configured.</div>';
  }
}

async function refreshContainers() {
  const list = $('#container-list');
  try {
    const data = await api(`/api/containers?${envQuery()}`);
    if (!data.configured) {
      list.innerHTML = '<div class="table-empty">Container inventory is not connected.</div>';
      $('#container-note').textContent = data.message;
      return;
    }
    $('#container-note').textContent = data.message;
    list.innerHTML = data.containers.length ? data.containers.map((container) => `
      <button class="container-row" data-service="${escapeHTML(container.service)}" title="Load recent logs for ${escapeHTML(container.service)}">
        <span><b>${escapeHTML(container.service)}</b><small>${escapeHTML(container.name)}</small></span>
        <span class="container-state ${escapeHTML(container.state)}"><i></i>${escapeHTML(container.state)}</span>
        <span class="container-detail">${escapeHTML(container.status)}</span>
      </button>`).join('') : '<div class="table-empty">No containers found in the configured project.</div>';
    $$('.container-row').forEach((button) => button.addEventListener('click', () => {
      $('#log-service').value = button.dataset.service;
      loadLogs();
    }));
  } catch (error) {
    list.innerHTML = '<div class="table-empty">Container inventory is unavailable.</div>';
    $('#container-note').textContent = error.message;
  }
}

async function loadLogs() {
  const service = $('#log-service').value;
  $('#log-output').textContent = `Loading ${service} logs…`;
  try {
    const data = await api(`/api/logs/${encodeURIComponent(service)}?${envQuery()}&tail=${$('#log-tail').value}`);
    $('#log-output').textContent = data.lines || '(No recent output)';
    $('#log-output').scrollTop = $('#log-output').scrollHeight;
  } catch (error) {
    $('#log-output').textContent = `${error.message}\n\nFor local Docker logs, enable the optional read-only socket proxy. In Kubernetes, configure pod-log access using a narrowly scoped service account.`;
  }
}

function costInputs() {
  const read = (id) => Number($(id).value);
  return {
    instance_type: $('#instance-type').value,
    node_count: read('#node-count'),
    ebs_gb: read('#ebs-gb'),
    s3_gb: read('#s3-gb'),
    nat_gateways: read('#nat-count'),
    nat_data_gb: read('#nat-data'),
    load_balancers: read('#load-balancers'),
    hours_per_month: read('#hours-month'),
    image_storage_gb: read('#images-gb'),
    replicas: read('#replicas'),
    container_cpu: read('#container-cpu'),
    container_memory_gb: read('#container-memory'),
    include_eks: $('#include-eks').checked,
  };
}

function renderCost(data) {
  state.cost = data;
  $('#cost-total').textContent = Number(data.monthly_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  $('#cost-annual').textContent = `$${Number(data.annual_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  $('#cost-breakdown').innerHTML = data.line_items.map((item) => `
    <div class="cost-line"><span>${escapeHTML(item.service)}</span><strong>$${Number(item.monthly_usd).toFixed(2)}</strong></div>`).join('');
  $('#container-allocation').textContent = `$${Number(data.container_plan.allocation_equivalent_usd).toFixed(2)} / mo`;
  $('#recommendations-list').innerHTML = data.recommendations.map((item) => `<li>${escapeHTML(item)}</li>`).join('');
  $('#cost-disclaimer').textContent = data.disclaimer;
}

let costTimer;
async function calculateCost() {
  clearTimeout(costTimer);
  costTimer = setTimeout(async () => {
    try {
      const data = await api('/api/cost-estimate', { method: 'POST', body: JSON.stringify(costInputs()) });
      renderCost(data);
    } catch (error) {
      $('#cost-disclaimer').textContent = error.message;
    }
  }, 180);
}

function appendMessage(role, content, meta = '') {
  const message = document.createElement('div');
  message.className = role === 'user' ? 'user-message' : 'assistant-message';
  const roleLabel = role === 'user' ? 'YOU' : 'FORGE ASSISTANT';
  const paragraph = document.createElement('p');
  paragraph.textContent = content;
  const label = document.createElement('span');
  label.className = 'message-role';
  label.textContent = roleLabel;
  message.append(label, paragraph);
  if (meta) {
    const detail = document.createElement('small');
    detail.className = 'message-meta';
    detail.textContent = meta;
    message.append(detail);
  }
  $('#chat-messages').append(message);
  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
}

async function sendChat(event) {
  event.preventDefault();
  const input = $('#chat-input');
  const prompt = input.value.trim();
  if (!prompt) return;
  input.value = '';
  appendMessage('user', prompt);
  $('#chat-send').disabled = true;
  document.body.classList.add('assistant-thinking');
  try {
    const response = await api(`/api/chat?${envQuery()}`, {
      method: 'POST',
      body: JSON.stringify({ prompt, max_tokens: 512 }),
    });
    const costText = response.cached ? 'Cached response · $0.00' : `${response.input_tokens} in / ${response.output_tokens} out · $${Number(response.cost_usd).toFixed(5)}`;
    appendMessage('assistant', response.text, `${response.provider} · ${costText}`);
    $('#llm-provider').textContent = response.provider.toUpperCase();
    $('#llm-caption').textContent = response.cached ? 'Response served from cache' : `${costText} estimated`;
    if (response.provider === 'mock') $('#assistant-mode').textContent = 'MOCK PROVIDER · CONNECT A KEY FOR LIVE MODEL RESPONSES';
  } catch (error) {
    appendMessage('assistant', `I could not reach the LLM gateway: ${error.message}`);
  } finally {
    $('#chat-send').disabled = false;
    document.body.classList.remove('assistant-thinking');
  }
}

async function askDocs(event) {
  event.preventDefault();
  const question = $('#docs-question').value.trim();
  if (!question) return;
  const button = $('#docs-submit');
  button.disabled = true;
  $('#docs-result').textContent = 'Searching indexed documentation…';
  try {
    const result = await api(`/api/ask?${envQuery()}`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    });
    const sources = (result.sources || []).map((source) =>
      `${source.file} · relevance ${source.score}`,
    ).join('  /  ');
    $('#docs-result').innerHTML = `<p>${escapeHTML(result.answer)}</p><div class="knowledge-sources"><span>${result.llm_used ? 'LLM SYNTHESIS' : 'RETRIEVAL / FALLBACK'}</span><span>${escapeHTML(sources || 'No matching source found')}</span></div>`;
  } catch (error) {
    $('#docs-result').textContent = `Documentation search unavailable: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function generateReport() {
  const button = $('#generate-report');
  button.disabled = true;
  button.textContent = 'Building snapshot…';
  try {
    state.report = await api('/api/reports', {
      method: 'POST',
      body: JSON.stringify({ environment: state.environment, cost_inputs: costInputs() }),
    });
    $('#report-preview').textContent = JSON.stringify(state.report, null, 2);
    $('#report-timestamp').textContent = `Generated ${new Date(state.report.generated_at).toLocaleString()}`;
    const file = new Blob([JSON.stringify(state.report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = `forge-${state.environment}-report-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast('Report generated and downloaded.');
  } catch (error) {
    toast(`Report unavailable: ${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = 'Generate report <span>↗</span>';
  }
}

async function simulateIncident() {
  try {
    await api(`/api/simulate-incident?${envQuery()}`, { method: 'POST', body: '{}' });
    await refreshIncidents();
    toast('Test incident recorded.');
  } catch (error) {
    toast(`Could not simulate incident: ${error.message}`);
  }
}

async function scoreDeploy(event) {
  event.preventDefault();
  const payload = {
    files_changed: Number($('#risk-files').value),
    lines_changed: Number($('#risk-lines').value),
    test_coverage: Number($('#risk-coverage').value),
    hour_of_day: Number($('#risk-hour').value),
    recent_failures: Number($('#risk-failures').value),
  };
  const button = $('#score-deploy');
  button.disabled = true;
  try {
    const result = await api(`/api/predict?${envQuery()}`, { method: 'POST', body: JSON.stringify(payload) });
    $('#risk-score').textContent = Number(result.risk_score).toFixed(3);
    $('#risk-level').textContent = `${result.risk_level} risk · ${result.model_version}`;
    $('#risk-result').classList.remove('low', 'medium', 'high');
    $('#risk-result').classList.add(result.risk_level);
  } catch (error) {
    $('#risk-level').textContent = `Model unavailable · ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function initNavigation() {
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    state.activeSection = visible.target.id;
    $$('.nav-item').forEach((link) => link.classList.toggle('active', link.hash === `#${state.activeSection}`));
  }, { rootMargin: '-15% 0px -70% 0px', threshold: [0, 0.2, 0.5] });
  $$('.content-wrap > section').forEach((section) => observer.observe(section));
}

function textureLabel(title, subtitle, accent) {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#171815';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = accent;
  ctx.lineWidth = 7;
  ctx.strokeRect(5, 5, canvas.width - 10, canvas.height - 10);
  ctx.fillStyle = accent;
  ctx.fillRect(25, 30, 18, 18);
  ctx.font = '500 30px Manrope, sans-serif';
  ctx.fillStyle = '#f0eee8';
  ctx.fillText(title.toUpperCase(), 60, 52, 420);
  ctx.font = '24px monospace';
  ctx.fillStyle = '#a5a39b';
  ctx.fillText(subtitle.toUpperCase(), 28, 205, 450);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeArchitectureScene() {
  const mount = $('#architecture-scene');
  const canvas = $('#architecture-canvas');
  if (!mount || !canvas) return;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
  } catch {
    mount.classList.add('scene-unavailable');
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x151612, 1);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  camera.position.set(0, 1.5, 7.8);
  camera.lookAt(0, 0, 0);
  const group = new THREE.Group();
  scene.add(group);
  scene.add(new THREE.HemisphereLight(0xf6e9cf, 0x171b1a, 2.1));
  const keyLight = new THREE.PointLight(0xff7438, 58, 18);
  keyLight.position.set(-4, 5, 5);
  scene.add(keyLight);
  const mintLight = new THREE.PointLight(0x74daa9, 30, 14);
  mintLight.position.set(5, -2, 4);
  scene.add(mintLight);

  const grid = new THREE.GridHelper(14, 28, 0x3e4a3f, 0x27302a);
  grid.position.y = -2.15;
  grid.material.transparent = true;
  grid.material.opacity = 0.35;
  group.add(grid);

  const nodes = [
    { id: 'portal', label: 'Portal', detail: 'Developer entry point', position: [-3.4, 0.6, 0], color: '#ff7438' },
    { id: 'docs', label: 'Docs assistant', detail: 'TF-IDF retrieval + RAG', position: [-1.25, 1.65, -0.5], color: '#ff925b' },
    { id: 'gateway', label: 'LLM gateway', detail: 'Provider, cache + usage', position: [1.0, 1.55, 0.45], color: '#ff7438' },
    { id: 'model', label: 'Model serving', detail: 'Deploy-risk API', position: [3.25, 0.45, -0.2], color: '#8ac9aa' },
    { id: 'aiops', label: 'AIOps agent', detail: 'Prometheus incident loop', position: [-2.2, -1.05, -0.5], color: '#f2bd68' },
    { id: 'metrics', label: 'Prometheus', detail: 'Metrics + PromQL', position: [0, -1.65, 0.2], color: '#8ac9aa' },
    { id: 'grafana', label: 'Grafana', detail: 'Mission Control', position: [2.45, -1.0, 0.5], color: '#8ac9aa' },
  ];
  const meshes = [];
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const connectionPairs = [[0, 1], [0, 2], [0, 3], [1, 2], [2, 4], [4, 5], [3, 5], [5, 6]];
  for (const [from, to] of connectionPairs) {
    const material = new THREE.LineDashedMaterial({ color: 0x9b795d, transparent: true, opacity: 0.55, dashSize: 0.12, gapSize: 0.08 });
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...nodes[from].position), new THREE.Vector3(...nodes[to].position),
    ]);
    const line = new THREE.Line(geometry, material);
    line.computeLineDistances();
    group.add(line);
  }

  for (const node of nodes) {
    const material = new THREE.MeshStandardMaterial({
      color: 0x1a1b17,
      emissive: new THREE.Color(node.color),
      emissiveIntensity: 0.11,
      metalness: 0.72,
      roughness: 0.28,
    });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(2.05, 0.86, 0.26), material);
    mesh.position.set(...node.position);
    mesh.userData = node;
    const label = new THREE.Mesh(
      new THREE.PlaneGeometry(1.98, 0.8),
      new THREE.MeshBasicMaterial({ map: textureLabel(node.label, node.detail, node.color), transparent: false }),
    );
    label.position.z = 0.136;
    mesh.add(label);
    group.add(mesh);
    meshes.push(mesh);
  }

  const core = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.38, 2),
    new THREE.MeshStandardMaterial({ color: 0xff793f, emissive: 0xf04d18, emissiveIntensity: 0.8, metalness: 0.3, roughness: 0.24, wireframe: true }),
  );
  core.position.set(0, 0, 1.1);
  group.add(core);
  const coreLight = new THREE.PointLight(0xff682f, 16, 5);
  coreLight.position.copy(core.position);
  group.add(coreLight);

  const particles = connectionPairs.map(([from, to], index) => {
    const particle = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 8), new THREE.MeshBasicMaterial({ color: index % 2 ? 0x8bd6ad : 0xff8953 }));
    particle.userData.path = [new THREE.Vector3(...nodes[from].position), new THREE.Vector3(...nodes[to].position)];
    particle.userData.offset = index / connectionPairs.length;
    group.add(particle);
    return particle;
  });

  function resize() {
    const width = Math.max(mount.clientWidth, 1);
    const height = Math.max(mount.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.position.z = width < 580 ? 12.5 : 7.8;
    camera.updateProjectionMatrix();
  }
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(mount);
  resize();

  let targetX = 0;
  let targetY = 0;
  let frame = 0;
  mount.addEventListener('pointermove', (event) => {
    const rect = mount.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    targetY = pointer.x * 0.12;
    targetX = pointer.y * 0.065;
  });
  mount.addEventListener('pointerleave', () => { targetX = 0; targetY = 0; });
  canvas.addEventListener('click', (event) => {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hitObject = raycaster.intersectObjects(meshes)[0]?.object;
    const hit = hitObject?.userData?.label ? hitObject : hitObject?.parent;
    if (hit?.userData?.label) {
      $('#node-inspector').innerHTML = `<b>${escapeHTML(hit.userData.label)}</b><span>${escapeHTML(hit.userData.detail)}</span>`;
      meshes.forEach((mesh) => { mesh.scale.setScalar(mesh === hit ? 1.09 : 1); });
    }
  });

  const clock = new THREE.Clock();
  function animate() {
    frame = requestAnimationFrame(animate);
    const elapsed = clock.getElapsedTime();
    group.rotation.y += (targetY - group.rotation.y) * 0.025;
    group.rotation.x += (targetX - group.rotation.x) * 0.025;
    core.rotation.x = elapsed * 0.22;
    core.rotation.y = elapsed * 0.34;
    particles.forEach((particle) => {
      const progress = (elapsed * 0.12 + particle.userData.offset) % 1;
      particle.position.lerpVectors(particle.userData.path[0], particle.userData.path[1], progress);
    });
    renderer.render(scene, camera);
  }
  animate();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) cancelAnimationFrame(frame);
    else animate();
  });
}

function makeBotScene() {
  const canvas = $('#bot-canvas');
  const root = canvas?.parentElement;
  if (!canvas || !root) return;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
  } catch {
    root.classList.add('bot-unavailable');
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 30);
  camera.position.set(0, 0.1, 6.3);
  scene.add(new THREE.HemisphereLight(0xfff0dc, 0x22251d, 2.2));
  const light = new THREE.PointLight(0xff783e, 42, 12);
  light.position.set(-2.4, 2.5, 4);
  scene.add(light);
  const rim = new THREE.PointLight(0x68c9a0, 22, 10);
  rim.position.set(3, -1, 2);
  scene.add(rim);
  const bot = new THREE.Group();
  scene.add(bot);

  const shell = new THREE.Mesh(new THREE.SphereGeometry(1.1, 36, 28), new THREE.MeshStandardMaterial({ color: 0x282722, metalness: 0.68, roughness: 0.27 }));
  shell.scale.set(1, 0.88, 0.8);
  bot.add(shell);
  const face = new THREE.Mesh(new THREE.BoxGeometry(1.32, 0.58, 0.2), new THREE.MeshStandardMaterial({ color: 0x141614, metalness: 0.4, roughness: 0.25, emissive: 0x07100c }));
  face.position.set(0, 0.05, 0.77);
  bot.add(face);
  const eyes = [];
  for (const x of [-0.34, 0.34]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.105, 16, 12), new THREE.MeshBasicMaterial({ color: 0x84e1b2 }));
    eye.position.set(x, 0.08, 0.9);
    bot.add(eye);
    eyes.push(eye);
  }
  const mouth = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.035, 0.025), new THREE.MeshBasicMaterial({ color: 0xff8148 }));
  mouth.position.set(0, -0.13, 0.9);
  bot.add(mouth);
  const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.45, 8), new THREE.MeshStandardMaterial({ color: 0xb8b2a5, metalness: 0.7 }));
  antenna.position.y = 1.12;
  bot.add(antenna);
  const antennaLight = new THREE.Mesh(new THREE.SphereGeometry(0.105, 16, 12), new THREE.MeshBasicMaterial({ color: 0xff7840 }));
  antennaLight.position.y = 1.36;
  bot.add(antennaLight);
  const earMaterial = new THREE.MeshStandardMaterial({ color: 0xf17441, metalness: 0.46, roughness: 0.24 });
  for (const x of [-1.06, 1.06]) {
    const ear = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.22, 6), earMaterial);
    ear.rotation.z = Math.PI / 2;
    ear.position.set(x, 0.03, 0.1);
    bot.add(ear);
  }

  let pointerX = 0;
  let pointerY = 0;
  root.addEventListener('pointermove', (event) => {
    const rect = root.getBoundingClientRect();
    pointerX = ((event.clientX - rect.left) / rect.width - 0.5) * 0.6;
    pointerY = ((event.clientY - rect.top) / rect.height - 0.5) * 0.22;
  });
  function resize() {
    const width = Math.max(root.clientWidth, 1);
    const height = Math.max(root.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(root);
  resize();
  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const time = clock.getElapsedTime();
    bot.rotation.y += (pointerX - bot.rotation.y) * 0.045;
    bot.rotation.x += (-pointerY - bot.rotation.x) * 0.045;
    bot.position.y = Math.sin(time * 1.25) * 0.08;
    eyes.forEach((eye) => { eye.position.x = (eye.position.x < 0 ? -0.34 : 0.34) + pointerX * 0.12; });
    mouth.scale.y = document.body.classList.contains('assistant-thinking') ? 1 + (Math.sin(time * 14) + 1) * 3 : 1;
    antennaLight.material.color.setHSL(0.06 + (Math.sin(time * 2) + 1) * 0.02, 0.8, 0.6);
    renderer.render(scene, camera);
  }
  animate();
}

function bindEvents() {
  $$('.env-tab').forEach((button) => button.addEventListener('click', async () => {
    state.environment = button.dataset.env;
    renderEnvironmentTabs();
    await Promise.all([refreshOverview(), refreshIncidents(), refreshContainers()]);
  }));
  $('#refresh-button').addEventListener('click', refreshAll);
  $('#containers-refresh').addEventListener('click', refreshContainers);
  $('#load-logs').addEventListener('click', loadLogs);
  $('#simulate-incident').addEventListener('click', simulateIncident);
  $('#chat-form').addEventListener('submit', sendChat);
  $('#docs-form').addEventListener('submit', askDocs);
  $('#risk-form').addEventListener('submit', scoreDeploy);
  $('#ops-auth-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const token = $('#ops-token').value.trim();
    if (token) sessionStorage.setItem('forge-ops-token', token);
    else sessionStorage.removeItem('forge-ops-token');
    $('#ops-auth-state').textContent = token ? 'Checking access…' : 'Token stays in this browser session.';
    await refreshContainers();
    const unlocked = $('#container-note').textContent === 'Read-only Docker Engine inventory.'
      || $('#container-note').textContent === 'Read-only Kubernetes pod inventory.';
    $('#ops-auth-state').textContent = unlocked ? 'Read-only inventory unlocked for this session.' : $('#container-note').textContent;
    toast(unlocked ? 'Read-only operations access enabled.' : 'Operations access was not verified.');
  });
  $('#cost-form').addEventListener('input', calculateCost);
  $('#cost-form').addEventListener('change', calculateCost);
  $('#generate-report').addEventListener('click', generateReport);
  $('#print-report').addEventListener('click', () => window.print());
  $('#chat-input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      $('#chat-form').requestSubmit();
    }
  });
}

async function refreshAll() {
  await Promise.all([refreshOverview(), refreshIncidents(), refreshContainers()]);
}

async function boot() {
  makeArchitectureScene();
  makeBotScene();
  initNavigation();
  bindEvents();
  try {
    const config = await api('/api/config');
    state.environments = config.environments;
    $('#llm-provider').textContent = 'READY';
    $('#llm-caption').textContent = 'Provider is shown after first request';
    renderEnvironmentTabs();
  } catch (error) {
    setApiState(false);
    $('#env-detail').textContent = `Portal API unavailable: ${error.message}`;
  }
  await refreshAll();
  calculateCost();
  setInterval(refreshAll, 20000);
}

boot();