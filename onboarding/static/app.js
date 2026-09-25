const el = id => document.getElementById(id);
let csrf, mode = 'signup', resolvedEmail = '', sequence = 0, timer, busy = false;
async function api(path, data) {
  const response = await fetch(path, data ? {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)} : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || 'The request could not finish.');
  return result;
}
function enable() { el('submit').disabled = busy || !csrf || !resolvedEmail || resolvedEmail !== el('email').value.trim(); }
for (const action of ['signup','login']) el(action).onclick = () => {
  if (busy) return;
  mode = action;
  for (const id of ['signup','login']) el(id).setAttribute('aria-pressed', String(id === mode));
  el('submit').textContent = mode === 'signup' ? 'Sign up' : 'Sign in';
};
el('email').addEventListener('input', () => {
  el('get-classes').disabled = true;
  el('class-output').textContent = ''; el('report-output').textContent = '';
  clearTimeout(timer); const current = ++sequence; resolvedEmail = ''; enable();
  el('school').textContent = 'Connect your school'; el('logo').hidden = true;
  el('error').textContent = '';
  el('discovery').textContent = 'Your email will be sent to ManageBac to find your school.';
  if (!el('email').validity.valid || !el('email').value) return;
  timer = setTimeout(async () => {
    const email = el('email').value.trim(); el('discovery').textContent = 'Finding your school…';
    try {
      const data = await api('/api/discover', {email});
      if (current !== sequence) return;
      resolvedEmail = email; el('school').textContent = data.school.name;
      el('discovery').textContent = `School found: ${data.school.origin}`;
      if (data.school.logo) { el('logo').src = data.school.logo; el('logo').hidden = false; }
      enable();
    } catch (e) { if (current === sequence) el('discovery').textContent = e.message; }
  }, 900);
});
el('logo').onerror = () => { el('logo').hidden = true; };
el('form').onsubmit = event => {
  event.preventDefault();
  if (mode === 'signup') el('overview').showModal(); else start(false);
};
el('cancel').onclick = () => el('overview').close();
el('understood').onclick = () => { el('overview').close(); start(true); };
async function start(understood) {
  el('get-classes').disabled = true;
  busy = true; enable(); el('email').disabled = true; el('password').disabled = true;
  el('error').textContent = ''; el('result').textContent = ''; el('checks').replaceChildren(); el('records').textContent = '';
  const password = el('password').value; el('password').value = '';
  try {
    await api('/api/signin', {email:resolvedEmail,password,mode,understood});
    while (true) {
      const state = await api('/api/state');
      el('records').textContent = JSON.stringify({authenticated:state.authenticated, verification:state.verification, capability_checks:state.capability_checks}, null, 2);
      el('checks').replaceChildren(...state.steps.map(step => {
        const li = document.createElement('li'); li.className = step.state;
        li.textContent = step.message; return li;
      }));
      if (!state.busy) {
        if (state.error) el('error').textContent = `${state.error.message} Reference: ${state.error.diagnostic_id}`;
        el('result').textContent = state.authenticated ? 'Sign-in verified. You can now run Get classes separately. ChatGPT is not connected.' : 'Sign-in could not be verified. Connection remains disabled.';
        el('get-classes').disabled = !state.authenticated;
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 750));
    }
  } catch(e) { el('error').textContent = e.message; }
  finally { busy = false; el('email').disabled = false; el('password').disabled = false; enable(); }
}
async function fetchClasses() {
  if (busy) return;
  busy = true; enable(); el('get-classes').disabled = true;
  el('email').disabled = true; el('password').disabled = true;
  el('class-status').textContent = 'Retrieving enrolled classes…';
  el('class-output').textContent = '';
  try {
    const data = await api('/api/tools/get_classes', {});
    el('class-output').textContent = JSON.stringify(data,null,2);
    el('class-status').textContent = data.error ? data.error.message : `${data.classes.length} classes. All pages retrieved.`;
    const state = await api('/api/state');
    el('get-classes').disabled = !state.authenticated;
  } catch (e) { el('class-status').textContent = e.message; el('get-classes').disabled = false; }
  finally { busy = false; el('email').disabled = false; el('password').disabled = false; enable(); }
}
el('get-classes').onclick = fetchClasses;
el('get-report').onclick = async () => {
  try {
    const data = await api('/api/reports');
    const status = data.export_status || {};
    const warning = status.state === 'full' ? 'Report folder full: new runs are NOT being saved. Move old runs out of Working/Test Reports.\n\n'
      : status.state === 'nearly_full' ? `Report folder nearly full (${status.runs}/${status.limit} runs).\n\n` : '';
    el('report-output').textContent = warning + JSON.stringify(data,null,2);
  }
  catch(e) { el('report-output').textContent = e.message; }
};
api('/api/bootstrap').then(async data => {
  csrf = data.csrf; enable(); el('get-report').disabled = !data.developer_mode;
  el('developer-status').textContent = data.developer_mode ? 'Developer mode: on. Login and class responses are saved in Working/Test Reports on Atlas. View the developer report for each saved file location.' : 'Developer mode: off. No detailed reports collected.';
  const state = await api('/api/state');
  el('get-classes').disabled = !state.authenticated;
  if (state.authenticated) el('result').textContent = 'Your verified session is available. Get classes runs separately.';
  await loadToolWorkbench();
}).catch(e => el('error').textContent = e.message);

async function loadToolWorkbench() {
  const catalogue = (await api('/api/tools')).tools;
  const picker = el('tool-picker');
  picker.replaceChildren();
  for (const tool of catalogue) {
    const option = document.createElement('option');
    option.value = tool.name; option.textContent = tool.name; picker.append(option);
  }
  picker.onchange = () => {
    const tool = catalogue.find(item => item.name === picker.value);
    el('tool-description').textContent = tool.description;
    el('tool-schema').textContent = JSON.stringify(tool.inputSchema, null, 2);
    const args = {};
    for (const name of tool.inputSchema.required || []) {
      args[name] = name === 'class_id' ? el('inspect-class').value :
        name === 'task_id' ? el('inspect-task').value : name === 'class_ids' ? [] : '';
    }
    el('tool-arguments').value = JSON.stringify(args, null, 2);
  };
  picker.onchange(); el('run-tool').disabled = false;
}
el('run-tool').onclick = async () => {
  if (busy) return;
  let args;
  try {
    args = JSON.parse(el('tool-arguments').value);
    if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error();
  } catch (_) { el('tool-workbench-status').textContent = 'Enter a JSON object matching the input schema.'; return; }
  busy = true; enable(); inspectControls(); el('run-tool').disabled = true;
  for (const id of ['email','password','get-classes','inspect-class','inspect-task']) el(id).disabled = true;
  inspectPayload = null; el('inspect-output').textContent = ''; el('inspect-download').disabled = true;
  el('tool-workbench-status').textContent = `Running ${el('tool-picker').value}…`;
  try {
    const payload = await api(`/api/tools/${el('tool-picker').value}`, args);
    inspectPayload = payload;
    el('inspect-output').textContent = JSON.stringify(payload, null, 2);
    el('inspect-download').disabled = false;
    el('tool-workbench-status').textContent = payload.error ? payload.error.message : 'Exact response is ready in the inspector above.';
  } catch (error) { el('tool-workbench-status').textContent = error.message; }
  finally {
    busy = false; el('run-tool').disabled = false;
    el('email').disabled = false; el('password').disabled = false;
    el('inspect-class').disabled = el('inspect-class').options.length < 2;
    el('inspect-task').disabled = el('inspect-task').options.length < 2;
    try { el('get-classes').disabled = !(await api('/api/state')).authenticated; }
    catch (_) { el('get-classes').disabled = true; }
    enable(); inspectControls();
  }
};

// This inspector calls the same account-scoped tools as MCP, not a second parser.
let inspectPayload = null;
function choices(id, rows, label) {
  const select = el(id);
  select.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = ''; placeholder.textContent = label; select.append(placeholder);
  for (const row of rows) {
    const option = document.createElement('option');
    option.value = row.id; option.textContent = row.name || row.title;
    select.append(option);
  }
  select.disabled = !rows.length;
}
function inspectControls() {
  el('inspect-tasks').disabled = busy || !el('inspect-class').value;
  el('inspect-files').disabled = busy || !el('inspect-class').value;
  el('inspect-detail').disabled = busy || !el('inspect-class').value || !el('inspect-task').value;
  window.classFileBrowser?.setBusy(busy || !el('inspect-class').value);
}
function clearInspection() {
  inspectPayload = null; el('inspect-output').textContent = '';
  el('inspect-download').disabled = true;
  choices('inspect-task', [], 'Get tasks first'); inspectControls();
  window.classFileBrowser?.reset();
}
new MutationObserver(() => {
  let rows = [];
  try { rows = JSON.parse(el('class-output').textContent).classes || []; } catch (_) {}
  choices('inspect-class', rows, rows.length ? 'Choose a class' : 'Get classes first');
  clearInspection();
}).observe(el('class-output'), {childList:true, subtree:true, characterData:true});
el('inspect-class').onchange = clearInspection;
el('inspect-task').onchange = inspectControls;
el('email').addEventListener('input', () => {
  choices('inspect-class', [], 'Get classes first'); clearInspection();
});
el('form').addEventListener('submit', () => {
  choices('inspect-class', [], 'Get classes first'); clearInspection();
});
async function inspectTool(name, options = {}) {
  if (busy || !el('inspect-class').value) return;
  const args = {class_id:el('inspect-class').value};
  if (name === 'get_task') args.task_id = el('inspect-task').value;
  if (name === 'get_class_files') Object.assign(args, options);
  busy = true; enable(); inspectControls();
  for (const id of ['email','password','get-classes','inspect-class','inspect-task']) el(id).disabled = true;
  inspectPayload = null; el('inspect-output').textContent = ''; el('inspect-download').disabled = true;
  el('inspect-status').textContent = `Running ${name}…`;
  try {
    const payload = await api(`/api/tools/${name}`, args);
    inspectPayload = payload;
    el('inspect-output').textContent = JSON.stringify(payload, null, 2);
    el('inspect-download').disabled = false;
    el('inspect-status').textContent = payload.error ? payload.error.message : 'Response ready. Review or download the exact JSON below.';
    if (name === 'get_tasks') choices('inspect-task', payload.tasks || [], 'Choose a task');
    if (name === 'get_class_files') window.classFileBrowser?.render(payload);
    if (payload.error?.code === 'session_expired') {
      choices('inspect-class', [], 'Sign in again, then get classes');
      choices('inspect-task', [], 'Get tasks first');
    }
  } catch (error) { el('inspect-status').textContent = error.message; }
  finally {
    busy = false; el('email').disabled = false; el('password').disabled = false;
    el('inspect-class').disabled = el('inspect-class').options.length < 2;
    el('inspect-task').disabled = el('inspect-task').options.length < 2;
    try { el('get-classes').disabled = !(await api('/api/state')).authenticated; }
    catch (_) { el('get-classes').disabled = true; }
    enable(); inspectControls();
  }
}
el('inspect-tasks').onclick = () => inspectTool('get_tasks');
el('inspect-files').onclick = () => inspectTool('get_class_files', {recursive:el('files-recursive').checked});
el('inspect-detail').onclick = () => inspectTool('get_task');
el('inspect-download').onclick = () => {
  if (!inspectPayload) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(inspectPayload,null,2)+'\n'], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'response.json';
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};

el('audit-tasks').onclick = async () => {
  if (busy) return;
  const log = message => { el('audit-status').textContent += message + '\n'; };
  el('audit-status').textContent = '';
  busy = true; enable(); inspectControls();
  for (const id of ['audit-tasks','email','password','get-classes','inspect-class','inspect-task']) el(id).disabled = true;
  let classes = 0, tasks = 0, failures = 0;
  const checked = new Set();
  const terminal = new Set(['session_expired','login_required','rate_limited']);
  const check = (payload, label) => {
    if (!payload.error) return true;
    failures++;
    log(`${label}: ERROR ${payload.error.code} — ${payload.error.message}`);
    if (terminal.has(payload.error.code)) throw new Error('Audit stopped: reconnect or wait before retrying.');
    return false;
  };
  try {
    if (!(await api('/api/state')).authenticated) throw new Error('Sign in first, then click Run all-task audit.');
    log('Retrieving enrolled classes…');
    const list = await api('/api/tools/get_classes', {});
    if (!check(list, 'Classes')) return;
    for (const item of list.classes) {
      if (checked.has(item.id)) continue;
      checked.add(item.id); classes++;
      log(`Class ${classes}/${list.classes.length}: ${item.name}`);
      const listing = await api('/api/tools/get_tasks', {class_id:item.id});
      if (!check(listing, 'Task list')) continue;
      log(`  ${listing.tasks.length} tasks listed`);
      for (const task of listing.tasks) {
        const result = await api('/api/tools/get_task', {class_id:item.id,task_id:task.id});
        tasks++;
        if (check(result, `  Task ${task.id} (${task.title})`)) log(`  OK ${task.id}: ${task.title}`);
      }
    }
    log('Audit finished.');
  } catch (error) { log(error.message); }
  finally {
    log(`Checked ${classes} classes and ${tasks} task details; ${failures} tool errors. Successful calls still need content review.`);
    busy = false;
    for (const id of ['audit-tasks','email','password']) el(id).disabled = false;
    el('inspect-class').disabled = el('inspect-class').options.length < 2;
    el('inspect-task').disabled = el('inspect-task').options.length < 2;
    try { el('get-classes').disabled = !(await api('/api/state')).authenticated; }
    catch (_) { el('get-classes').disabled = true; }
    enable(); inspectControls();
  }
};
