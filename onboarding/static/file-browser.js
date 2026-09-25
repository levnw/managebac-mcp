// A view of get_class_files JSON, never a second scraper or a binary proxy.
(() => {
  let current = null, loaded = false, disabled = true;
  const folders = new Map();
  const root = document.getElementById('files-root');
  const up = document.getElementById('files-up');
  const recursive = document.getElementById('files-recursive');
  const location = document.getElementById('files-location');
  const folderList = document.getElementById('files-folders');
  const fileList = document.getElementById('files-items');
  function setBusy(value) {
    disabled = value;
    root.disabled = value || !loaded;
    up.disabled = value || !loaded || !current || !folders.has(current);
    recursive.disabled = value;
    for (const button of folderList.querySelectorAll('button')) button.disabled = value;
  }
  function openFolder(id) {
    if (disabled) return;
    inspectTool('get_class_files', {...(id ? {folder_id:id} : {}), recursive:recursive.checked});
  }
  root.onclick = () => openFolder(null);
  up.onclick = () => openFolder(folders.get(current)?.parent_id || null);
  function reset() {
    current = null; loaded = false; folders.clear();
    folderList.replaceChildren(); fileList.replaceChildren();
    location.textContent = 'Choose a class and get its files.';
    setBusy(disabled);
  }
  function render(payload) {
    // Do not leave an old successful listing looking like the failed result.
    folderList.replaceChildren(); fileList.replaceChildren();
    if (payload.error) {
      loaded = false;
      location.textContent = payload.error.message;
      setBusy(disabled); return;
    }
    current = payload.folder_id || null; loaded = true;
    for (const folder of payload.folders) folders.set(folder.id, folder);
    const name = current ? (folders.get(current)?.name || `Folder ${current}`) : 'Class files';
    location.textContent = `${name}: ${payload.files.length} files, ${payload.folders.length} folders` +
      (payload.recursive ? ' (includes descendants).' : ' (this directory only).');
    for (const folder of payload.folders) {
      const li = document.createElement('li'), button = document.createElement('button');
      button.textContent = folder.name; button.onclick = () => openFolder(folder.id);
      li.append(button); folderList.append(li);
    }
    for (const file of payload.files) {
      const li = document.createElement('li');
      // Source-derived URLs never become executable markup or javascript: links.
      let safe = false;
      try { const url = new URL(file.url); safe = url.protocol === 'https:' && !url.username && !url.password; } catch (_) {}
      const label = document.createElement(safe ? 'a' : 'span');
      label.textContent = file.name;
      if (safe) { label.href = file.url; label.target = '_blank'; label.rel = 'noopener noreferrer'; }
      li.append(label);
      const info = document.createElement('small');
      const parts = [];
      if (file.folder_id) parts.push(folders.get(file.folder_id)?.name || `Folder ${file.folder_id}`);
      if (file.size_bytes !== undefined) parts.push(`${file.size_bytes.toLocaleString()} bytes`);
      else if (file.size_display) parts.push(file.size_display);
      if (file.uploaded_by) parts.push(`by ${file.uploaded_by}`);
      info.textContent = parts.length ? ` — ${parts.join(' · ')}` : '';
      li.append(info); fileList.append(li);
    }
    setBusy(disabled);
  }
  window.classFileBrowser = {render, reset, setBusy};
  setBusy(true);
})();
