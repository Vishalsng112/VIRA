// ─── Modules ────────────────────────────────────────────
async function loadModules() {
  try {
    const resp = await fetch('/modules');
    const modules = await resp.json();
    const list = document.getElementById('module-list');
    if (!modules.length) {
      list.innerHTML = '<li>No modules loaded</li>';
      return;
    }
    list.innerHTML = modules.map(m => `
      <li>
        <span class="name">${m.name}</span>
        <span class="status-badge ${m.running ? '' : 'stopped'}">${m.running ? '● Running' : '● Stopped'}</span>
      </li>
    `).join('');
  } catch (e) {
    document.getElementById('module-list').innerHTML = '<li>Error loading modules</li>';
    console.error(e);
  }
}


// Redirect to login if we get 401
async function fetchWithAuth(url, opts = {}) {
  const resp = await fetch(url, opts);
  if (resp.status === 401) {
    window.location.href = '/login';
    return;
  }
  return resp;
}

// ─── Live Events (SSE) ──────────────────────────────────
let eventCount = 0;
const eventLog = document.getElementById('event-log');

function connectEventStream() {
  const eventSource = new EventSource('/events/stream', { withCredentials: true });
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      addEventToLog(data);
    } catch (e) {
      // ignore
    }
  };
  eventSource.onerror = () => {
    // Auto-reconnect on error (including 401)
    eventSource.close();
    setTimeout(connectEventStream, 3000);
  };
}

function addEventToLog(event) {
  eventCount++;
  document.getElementById('event-count').textContent = eventCount;

  const entry = document.createElement('div');
  entry.className = 'event-entry';
  const time = new Date(event.timestamp * 1000).toLocaleTimeString();
  const priority = event.priority || 'NORMAL';
  entry.innerHTML = `
    <span class="time">${time}</span>
    <span class="type">${event.type}</span>
    <span class="data">${JSON.stringify(event.data)}</span>
    <span class="priority ${priority}">${priority}</span>
  `;
  eventLog.prepend(entry);
  // limit visible entries
  while (eventLog.children.length > 200) {
    eventLog.removeChild(eventLog.lastChild);
  }
}

// ─── Load Module ────────────────────────────────────────
document.getElementById('load-module-btn').addEventListener('click', async () => {
  const path = document.getElementById('module-path').value.trim();
  if (!path) return;
  try {
    const resp = await fetch('/modules/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ module_path: path })
    });
    if (resp.ok) {
      alert('Module loaded successfully');
      loadModules();
    } else {
      const err = await resp.json();
      alert('Failed: ' + (err.detail || 'unknown error'));
    }
  } catch (e) {
    alert('Error: ' + e.message);
  }
});

// ─── Publish Event ──────────────────────────────────────
document.getElementById('publish-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const type = document.getElementById('event-type').value.trim();
  const dataStr = document.getElementById('event-data').value.trim();
  let data;
  try {
    data = JSON.parse(dataStr);
  } catch {
    alert('Invalid JSON in Data field');
    return;
  }
  const resultDiv = document.getElementById('publish-result');
  try {
    const resp = await fetch('/events/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include', 
      body: JSON.stringify({ type, data, source: 'webui' })
    });
    const json = await resp.json();
    if (resp.ok) {
      resultDiv.innerHTML = `✅ Published (correlation: ${json.correlation_id})`;
      resultDiv.style.color = '#2e7d32';
    } else {
      resultDiv.innerHTML = `❌ Error: ${json.detail || 'unknown'}`;
      resultDiv.style.color = '#c62828';
    }
  } catch (err) {
    resultDiv.innerHTML = `❌ Error: ${err.message}`;
    resultDiv.style.color = '#c62828';
  }
});

// ─── Init ───────────────────────────────────────────────
loadModules();
connectEventStream();

// Refresh modules every 30s
setInterval(loadModules, 30000);