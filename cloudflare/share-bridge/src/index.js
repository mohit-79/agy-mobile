// Easy memorable person names
const PERSON_NAMES = [
  'alex', 'maya', 'leo', 'sam', 'zack', 'olivia', 'noah', 'emma', 'liam', 'sophia',
  'lucas', 'mia', 'ethan', 'aria', 'mason', 'chloe', 'logan', 'zoe', 'jack', 'lily',
  'ryan', 'grace', 'luke', 'eva', 'owen', 'ella', 'caleb', 'mila', 'nathan', 'nora',
  'eli', 'riley', 'adam', 'ivy', 'ian', 'ruby', 'aaron', 'clara', 'felix', 'alice',
  'oscar', 'jade', 'finn', 'hazel', 'max', 'luna', 'hugo', 'stella', 'kai', 'elena'
];

function getCategory(fileName, mime) {
  const ext = (fileName.split('.').pop() || '').toLowerCase();
  const mimeLower = (mime || '').toLowerCase();

  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'heic', 'bmp'].includes(ext) || mimeLower.startsWith('image/')) return 'img';
  if (['mp4', 'mkv', 'mov', 'avi', 'webm', 'flv', 'wmv'].includes(ext) || mimeLower.startsWith('video/')) return 'vid';
  if (['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a'].includes(ext) || mimeLower.startsWith('audio/')) return 'music';
  if (['apk', 'xapk', 'aab'].includes(ext)) return 'apk';
  if (['pdf', 'doc', 'docx', 'txt', 'md', 'xls', 'xlsx', 'ppt', 'pptx'].includes(ext)) return 'doc';
  if (['zip', 'tar', 'gz', '7z', 'rar'].includes(ext)) return 'zip';
  return 'file';
}

function getRandomName() {
  const idx = Math.floor(Math.random() * PERSON_NAMES.length);
  return PERSON_NAMES[idx];
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': '*',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // 1. API Upload
    if (request.method === 'POST' && (path === '/api/upload' || path === '/upload')) {
      try {
        const contentType = request.headers.get('content-type') || '';
        let fileBuffer, fileName, fileMime;

        if (contentType.includes('multipart/form-data')) {
          const formData = await request.formData();
          const file = formData.get('file');
          if (!file) return new Response('Missing file in form data', { status: 400, headers: corsHeaders });
          fileBuffer = await file.arrayBuffer();
          fileName = file.name || 'file.bin';
          fileMime = file.type || 'application/octet-stream';
        } else {
          fileBuffer = await request.arrayBuffer();
          fileName = request.headers.get('x-filename') || 'file.bin';
          fileMime = contentType || 'application/octet-stream';
        }

        const category = getCategory(fileName, fileMime);
        let personName = getRandomName();

        // Check if name already taken in KV, append small random suffix if collision
        let lookupKey = `slug:${category}:${personName}`;
        let existing = await env.SHARE_FILES.get(lookupKey);
        if (existing) {
          const suffix = Math.floor(10 + Math.random() * 90);
          personName = `${personName}${suffix}`;
          lookupKey = `slug:${category}:${personName}`;
        }

        const fileKey = `data:${category}:${personName}`;
        const metaKey = `meta:${category}:${personName}`;

        const metadata = {
          category,
          name: personName,
          filename: fileName,
          mime: fileMime,
          size: fileBuffer.byteLength,
          uploadedAt: Date.now()
        };

        // 24 Hour TTL (86400s)
        await env.SHARE_FILES.put(fileKey, fileBuffer, { expirationTtl: 86400 });
        await env.SHARE_FILES.put(metaKey, JSON.stringify(metadata), { expirationTtl: 86400 });
        await env.SHARE_FILES.put(lookupKey, '1', { expirationTtl: 86400 });

        const friendlyUrl = `${url.origin}/${category}/${personName}`;

        const isCli = (request.headers.get('user-agent') || '').toLowerCase().includes('curl');
        if (isCli) {
          return new Response(`${friendlyUrl}\n`, {
            headers: { 'Content-Type': 'text/plain', ...corsHeaders }
          });
        }

        return new Response(JSON.stringify({
          success: true,
          category,
          person: personName,
          filename: fileName,
          url: friendlyUrl
        }), {
          headers: { 'Content-Type': 'application/json', ...corsHeaders }
        });
      } catch (err) {
        return new Response(`Upload failed: ${err.message}`, { status: 500, headers: corsHeaders });
      }
    }

    // 2. Friendly Download Handler: /:category/:personName
    const pathParts = path.replace(/^\/+|\/+$/g, '').split('/');
    if (request.method === 'GET' && pathParts.length === 2 && pathParts[0] !== 'api' && pathParts[0] !== 'f') {
      const [category, personName] = pathParts;
      const fileKey = `data:${category}:${personName}`;
      const metaKey = `meta:${category}:${personName}`;

      const metaRaw = await env.SHARE_FILES.get(metaKey);
      const fileBytes = await env.SHARE_FILES.get(fileKey, { type: 'arrayBuffer' });

      if (fileBytes) {
        let meta = { filename: `${personName}`, mime: 'application/octet-stream' };
        if (metaRaw) {
          try { meta = JSON.parse(metaRaw); } catch (e) {}
        }

        const isDownload = url.searchParams.has('dl') || request.headers.get('user-agent')?.includes('curl');
        const disposition = isDownload
          ? `attachment; filename="${meta.filename}"`
          : `inline; filename="${meta.filename}"`;

        return new Response(fileBytes, {
          headers: {
            'Content-Type': meta.mime,
            'Content-Disposition': disposition,
            ...corsHeaders
          }
        });
      }
    }

    // Backwards compatibility for /f/:id
    if (request.method === 'GET' && path.startsWith('/f/')) {
      const id = path.substring(3).split('/')[0];
      const metaRaw = await env.SHARE_FILES.get(`meta:${id}`);
      const fileBytes = await env.SHARE_FILES.get(`file:${id}`, { type: 'arrayBuffer' });
      if (fileBytes) {
        let meta = { name: 'download', mime: 'application/octet-stream' };
        if (metaRaw) { try { meta = JSON.parse(metaRaw); } catch(e){} }
        return new Response(fileBytes, {
          headers: {
            'Content-Type': meta.mime,
            'Content-Disposition': `attachment; filename="${meta.name}"`,
            ...corsHeaders
          }
        });
      }
    }

    // 3. Web UI
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Harjani Share</title>
  <style>
    :root { --bg: #09090b; --card: #18181b; --border: #27272a; --text: #fafafa; --accent: #ff0055; --sub: #a1a1aa; }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px; }
    .card { width: 100%; max-width: 520px; background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 32px; box-shadow: 0 20px 40px rgba(0,0,0,0.6); }
    h1 { font-size: 24px; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.5px; }
    h1 span { color: var(--accent); }
    p.desc { font-size: 14px; color: var(--sub); margin-bottom: 24px; }
    .dropzone { border: 2px dashed var(--border); border-radius: 14px; padding: 40px 20px; text-align: center; cursor: pointer; transition: all 0.2s; background: rgba(255,255,255,0.02); }
    .dropzone:hover, .dropzone.drag { border-color: var(--accent); background: rgba(255,0,85,0.05); }
    .dropzone svg { width: 44px; height: 44px; stroke: var(--sub); margin-bottom: 12px; }
    .file-input { display: none; }
    .res { margin-top: 24px; padding: 18px; background: #27272a; border-radius: 14px; display: none; animation: fadeIn 0.3s ease; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
    .res-badge { display: inline-block; background: var(--accent); color: white; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 3px 8px; border-radius: 6px; margin-bottom: 8px; }
    .res-link { word-break: break-all; color: #38bdf8; font-family: monospace; font-size: 15px; font-weight: 600; text-decoration: none; display: block; margin: 8px 0 14px 0; }
    .curl-box { background: #000; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 12px; color: #4ade80; margin-top: 18px; word-break: break-all; }
    .actions { display: flex; gap: 8px; }
    .btn { background: #3f3f46; color: white; border: none; padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
    .btn:hover { background: #52525b; }
    .btn.primary { background: var(--accent); }
    .btn.primary:hover { background: #e0004c; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Harjani <span>Share</span></h1>
    <p class="desc">Memorable links: <code>/img/maya</code>, <code>/vid/leo</code>, <code>/apk/sam</code></p>

    <div class="dropzone" id="dropzone" onclick="document.getElementById('file').click()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      <div id="dropText">Drop file here or click to browse</div>
      <input type="file" id="file" class="file-input" onchange="uploadFile(this.files[0])">
    </div>

    <div id="result" class="res">
      <span class="res-badge" id="resCategory">FILE</span>
      <div style="font-size: 13px; color: var(--sub);" id="resFileName">file.png</div>
      <a id="resUrl" class="res-link" target="_blank"></a>
      <div class="actions">
        <button class="btn primary" onclick="copyLink()">Copy Link</button>
        <a id="resDownload" class="btn" target="_blank">Open / Download</a>
      </div>
    </div>

    <div class="curl-box">
      <strong>AGY / CLI Command:</strong><br>
      <code>curl -F "file=@yourfile" ${url.origin}/api/upload</code>
    </div>
  </div>

  <script>
    const dropzone = document.getElementById('dropzone');
    ['dragenter', 'dragover'].forEach(n => dropzone.addEventListener(n, e => { e.preventDefault(); dropzone.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(n => dropzone.addEventListener(n, e => { e.preventDefault(); dropzone.classList.remove('drag'); }));
    dropzone.addEventListener('drop', e => { if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]); });

    async function uploadFile(file) {
      if (!file) return;
      document.getElementById('dropText').innerText = 'Uploading ' + file.name + '...';
      const fd = new FormData();
      fd.append('file', file);
      try {
        const r = await fetch('/api/upload', { method: 'POST', body: fd });
        const data = await r.json();
        document.getElementById('result').style.display = 'block';
        document.getElementById('resCategory').innerText = data.category;
        document.getElementById('resFileName').innerText = data.filename;
        document.getElementById('resUrl').innerText = data.url;
        document.getElementById('resUrl').href = data.url;
        document.getElementById('resDownload').href = data.url;
        document.getElementById('dropText').innerText = 'Drop another file or browse';
      } catch (err) {
        alert('Upload failed: ' + err.message);
        document.getElementById('dropText').innerText = 'Drop file here or browse';
      }
    }
    function copyLink() {
      navigator.clipboard.writeText(document.getElementById('resUrl').href);
      alert('Copied friendly link to clipboard!');
    }
  </script>
</body>
</html>`;

    return new Response(html, {
      headers: { 'Content-Type': 'text/html; charset=utf-8', ...corsHeaders }
    });
  }
};
