/**
 * Cloudflare Worker: Edge Gatekeeper for agy.harjani.me
 * 
 * 1. Blocks unauthenticated visitors before they reach Termux.
 * 2. Never exposes PIN or auth secrets in HTML/client-side JS.
 * 3. Transparently proxies authenticated WebSockets and HTTP requests to the origin tunnel.
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const cookieHeader = request.headers.get('Cookie') || '';

    const expectedPin = env.AUTH_PIN;
    const secretToken = env.SESSION_SECRET;

    // 1. Check if client has valid session cookie
    const hasValidSession = cookieHeader.includes(`agy_session=${secretToken}`);

    // 2. Handle Login POST Request
    if (request.method === 'POST' && path === '/edge-auth/login') {
      try {
        let enteredPin = '';
        const contentType = request.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const body = await request.json();
          enteredPin = (body.pin || '').toString().trim();
        } else {
          const formData = await request.formData();
          enteredPin = (formData.get('pin') || '').toString().trim();
        }

        if (enteredPin === expectedPin) {
          // Return HttpOnly secure cookie valid for 30 days
          return new Response(JSON.stringify({ success: true }), {
            headers: {
              'Content-Type': 'application/json',
              'Set-Cookie': `agy_session=${secretToken}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax`
            }
          });
        } else {
          return new Response(JSON.stringify({ success: false, error: 'Invalid PIN' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' }
          });
        }
      } catch (e) {
        return new Response(JSON.stringify({ success: false, error: 'Bad Request' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }

    // 3. Handle Logout Request
    if (path === '/edge-auth/logout') {
      return new Response(JSON.stringify({ success: true }), {
        headers: {
          'Content-Type': 'application/json',
          'Set-Cookie': `agy_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`
        }
      });
    }

    // 4. If not authenticated:
    if (!hasValidSession) {
      // For API or WebSocket requests, reject immediately with 401
      if (request.headers.get('Upgrade') === 'websocket' || path.startsWith('/api/') || path.startsWith('/ws')) {
        return new Response('Unauthorized: Edge PIN Authentication Required', { status: 401 });
      }

      // For browser navigation, display secure edge login screen
      return new Response(getSecureLoginHtml(), {
        headers: { 'Content-Type': 'text/html; charset=utf-8' }
      });
    }

    // 5. Authenticated: Transparently forward request + WebSocket to origin tunnel
    // We remove the worker trigger to let Cloudflare Tunnel / Origin process it directly
    const originRequest = new Request(request.url, {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: 'follow'
    });

    // Strip client-side overlay blocking on the returned HTML so terminal is ready immediately
    const originResponse = await fetch(originRequest);
    const contentType = originResponse.headers.get('content-type') || '';

    if (contentType.includes('text/html') && originResponse.status === 200) {
      let html = await originResponse.text();
      // Remove the old hardcoded client PIN check and unhide terminal automatically
      html = html.replace(/authToken/g, 'true');
      html = html.replace(/authOverlay\.style\.display = 'flex'/g, "authOverlay.style.display = 'none'");
      return new Response(html, {
        status: originResponse.status,
        headers: originResponse.headers
      });
    }

    return originResponse;
  }
};

function getSecureLoginHtml() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AGY // Access Lock</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
    body { background: #09090b; color: #fafafa; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
    .card { width: 100%; max-width: 380px; background: #141418; border: 1px solid #27272a; border-radius: 18px; padding: 32px 28px; box-shadow: 0 25px 50px rgba(0,0,0,0.8); text-align: center; }
    .badge { display: inline-block; background: #27272a; color: #a1a1aa; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; letter-spacing: 1px; margin-bottom: 16px; }
    h1 { font-size: 22px; font-weight: 700; margin-bottom: 8px; letter-spacing: -0.5px; }
    h1 span { color: #ff0055; }
    p { font-size: 13px; color: #71717a; margin-bottom: 24px; line-height: 1.5; }
    .input-box { width: 100%; background: #09090b; border: 1px solid #3f3f46; border-radius: 10px; padding: 14px; color: #fff; font-size: 20px; text-align: center; letter-spacing: 6px; outline: none; margin-bottom: 16px; transition: border-color 0.2s; }
    .input-box:focus { border-color: #ff0055; }
    .btn { width: 100%; background: #ff0055; color: white; border: none; padding: 13px; border-radius: 10px; font-size: 14px; font-weight: 700; cursor: pointer; transition: background 0.2s; }
    .btn:hover { background: #e0004c; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .error { color: #ef4444; font-size: 12px; margin-top: 12px; display: none; }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">SECURE GATEWAY</div>
    <h1>AGY <span>TERMINAL</span></h1>
    <p>Protected by Cloudflare Edge Verification.<br>Enter your master PIN to unlock session.</p>
    
    <input type="password" id="pin" class="input-box" placeholder="••••••" maxlength="12" autofocus autocomplete="off">
    <button id="btnUnlock" class="btn" onclick="submitAuth()">UNLOCK TERMINAL</button>
    <div id="errMsg" class="error">Incorrect PIN. Try again.</div>
  </div>

  <script>
    const pinInput = document.getElementById('pin');
    const errMsg = document.getElementById('errMsg');
    const btnUnlock = document.getElementById('btnUnlock');

    pinInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitAuth();
    });

    async function submitAuth() {
      const pin = pinInput.value.trim();
      if (!pin) return;
      btnUnlock.disabled = true;
      btnUnlock.innerText = 'VERIFYING...';
      errMsg.style.display = 'none';

      try {
        const res = await fetch('/edge-auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin })
        });
        const data = await res.json();
        if (data.success) {
          window.location.reload();
        } else {
          errMsg.style.display = 'block';
          pinInput.value = '';
          pinInput.focus();
          btnUnlock.disabled = false;
          btnUnlock.innerText = 'UNLOCK TERMINAL';
        }
      } catch (err) {
        errMsg.innerText = 'Connection error. Try again.';
        errMsg.style.display = 'block';
        btnUnlock.disabled = false;
        btnUnlock.innerText = 'UNLOCK TERMINAL';
      }
    }
  </script>
</body>
</html>`;
}
