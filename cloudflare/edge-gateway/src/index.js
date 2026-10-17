/**
 * Cloudflare Worker: Zero-Trust Edge Gatekeeper for AGY Workstation & Mobile
 * 
 * 1. Zero-Trust Edge Pre-Authentication (PIN protected).
 * 2. Dynamic origin tunnel registry (/api/tunnel-url).
 * 3. Transparent proxying for HTTP and WebSockets directly to the origin tunnel.
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const cookieHeader = request.headers.get('Cookie') || '';

    const expectedPin = env.AUTH_PIN || '29105';
    const secretToken = env.SESSION_SECRET || 'harjani_agy_sec_token_889922';

    // 1. Dynamic Tunnel Registration Endpoint (invoked by start.py / start.bat)
    if (path === '/api/tunnel-url') {
      if (request.method === 'POST') {
        try {
          const authHeader = request.headers.get('x-auth-pin') || '';
          const body = await request.json();
          if (authHeader === expectedPin || body.pin === expectedPin) {
            const tunnelUrl = (body.url || '').trim().replace(/\/+$/, '');
            if (tunnelUrl) {
              if (env.TUNNEL_KV) {
                await env.TUNNEL_KV.put('agy_tunnel_url', tunnelUrl);
                await env.TUNNEL_KV.put('agypc_tunnel_url', tunnelUrl);
              }
              return new Response(JSON.stringify({ success: true, url: tunnelUrl }), {
                headers: {
                  'Content-Type': 'application/json',
                  'Cache-Control': 'no-store, no-cache, must-revalidate'
                }
              });
            }
          }
          return new Response(JSON.stringify({ success: false, error: 'Unauthorized or invalid URL' }), { status: 401 });
        } catch (e) {
          return new Response(JSON.stringify({ success: false, error: e.message }), { status: 400 });
        }
      } else {
        let currentUrl = null;
        if (env.TUNNEL_KV) {
          currentUrl = await env.TUNNEL_KV.get('agy_tunnel_url') || await env.TUNNEL_KV.get('agypc_tunnel_url');
        }
        return new Response(JSON.stringify({ url: currentUrl || env.TUNNEL_ORIGIN || null }), {
          headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'no-store, no-cache, must-revalidate'
          }
        });
      }
    }

    // 2. Check if client has valid session cookie
    const hasValidSession = cookieHeader.includes(`agy_session=${secretToken}`) || cookieHeader.includes(`agypc_session=${secretToken}`);

    // 3. Handle Login POST Request
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

    // 4. Handle Logout Request
    if (path === '/edge-auth/logout') {
      return new Response(JSON.stringify({ success: true }), {
        headers: {
          'Content-Type': 'application/json',
          'Set-Cookie': `agy_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax`
        }
      });
    }

    // 5. If not authenticated:
    if (!hasValidSession) {
      if (request.headers.get('Upgrade') === 'websocket' || path.startsWith('/api/') || path.startsWith('/ws')) {
        return new Response('Unauthorized: Edge PIN Authentication Required', { status: 401 });
      }

      return new Response(getSecureLoginHtml(), {
        headers: { 'Content-Type': 'text/html; charset=utf-8' }
      });
    }

    // 6. Authenticated: Fetch target tunnel URL
    let targetTunnel = null;
    if (env.TUNNEL_KV) {
      targetTunnel = await env.TUNNEL_KV.get('agy_tunnel_url') || await env.TUNNEL_KV.get('agypc_tunnel_url');
    }
    if (!targetTunnel && env.TUNNEL_ORIGIN) {
      targetTunnel = env.TUNNEL_ORIGIN;
    }

    if (!targetTunnel) {
      return new Response(getWaitingForTunnelHtml(), {
        headers: { 'Content-Type': 'text/html; charset=utf-8' }
      });
    }

    // 7. Proxy request & WebSockets directly to the origin tunnel
    const targetUrl = new URL(targetTunnel);
    const destUrl = new URL(url.pathname + url.search, targetUrl.origin);

    const proxyHeaders = new Headers(request.headers);
    proxyHeaders.set('Host', targetUrl.host);
    proxyHeaders.set('X-Forwarded-Host', url.host);
    proxyHeaders.set('X-Forwarded-Proto', url.protocol.replace(':', ''));

    const isWs = request.headers.get('Upgrade') === 'websocket';
    const reqInit = {
      method: request.method,
      headers: proxyHeaders,
      redirect: 'follow'
    };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      reqInit.body = request.body;
    }

    const proxyRequest = new Request(destUrl.toString(), reqInit);

    try {
      const originResponse = await fetch(proxyRequest);
      if (isWs) {
        return originResponse;
      }
      const contentType = originResponse.headers.get('content-type') || '';

      // If HTML, automatically unhide terminal so user lands straight into the session
      if (contentType.includes('text/html') && originResponse.status === 200) {
        let html = await originResponse.text();
        html = html.replace(/authOverlay\.style\.display = 'flex'/g, "authOverlay.style.display = 'none'");
        return new Response(html, {
          status: originResponse.status,
          headers: originResponse.headers
        });
      }

      return originResponse;
    } catch (err) {
      return new Response(getTunnelErrorHtml(targetTunnel, err.message), {
        status: 502,
        headers: { 'Content-Type': 'text/html; charset=utf-8' }
      });
    }
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
    body { background: #030712; color: #fafafa; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
    .card { width: 100%; max-width: 400px; background: #090e1a; border: 1px solid rgba(0, 255, 204, 0.3); border-radius: 18px; padding: 36px 30px; box-shadow: 0 25px 50px rgba(0,0,0,0.9); text-align: center; }
    .badge { display: inline-block; background: rgba(0, 255, 204, 0.1); color: #00ffcc; border: 1px solid rgba(0, 255, 204, 0.4); font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; letter-spacing: 1.5px; margin-bottom: 16px; }
    h1 { font-size: 24px; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.5px; }
    h1 span { color: #00ffcc; text-shadow: 0 0 10px rgba(0,255,204,0.5); }
    p { font-size: 13px; color: #94a3b8; margin-bottom: 24px; line-height: 1.6; }
    .input-box { width: 100%; background: #030712; border: 1px solid #334155; border-radius: 10px; padding: 14px; color: #00ffcc; font-size: 22px; text-align: center; letter-spacing: 8px; outline: none; margin-bottom: 16px; transition: all 0.2s; }
    .input-box:focus { border-color: #00ffcc; box-shadow: 0 0 12px rgba(0,255,204,0.3); }
    .btn { width: 100%; background: #00ffcc; color: #030712; border: none; padding: 14px; border-radius: 10px; font-size: 14px; font-weight: 800; letter-spacing: 1px; cursor: pointer; transition: all 0.2s; }
    .btn:hover { background: #38bdf8; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .error { color: #f87171; font-size: 12px; margin-top: 12px; display: none; }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">ZERO-TRUST EDGE GATEKEEPER</div>
    <h1>AGY <span>2.0</span></h1>
    <p>Protected by Cloudflare Edge Gateway.<br>Enter master PIN to unlock session.</p>
    
    <input type="password" id="pin" class="input-box" placeholder="••••" maxlength="12" autofocus autocomplete="off">
    <button id="btnUnlock" class="btn" onclick="submitAuth()">UNLOCK WORKSTATION</button>
    <div id="errMsg" class="error">Incorrect PIN. Try again.</div>
  </div>

  <script>
    async function submitAuth() {
      const pin = document.getElementById('pin').value.trim();
      const btn = document.getElementById('btnUnlock');
      const err = document.getElementById('errMsg');
      if (!pin) return;

      btn.disabled = true;
      btn.textContent = 'VERIFYING...';
      err.style.display = 'none';

      try {
        const res = await fetch('/edge-auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin })
        });
        const data = await res.json();
        if (data.success) {
          localStorage.setItem('agy_key', pin);
          window.location.reload();
        } else {
          err.style.display = 'block';
          btn.disabled = false;
          btn.textContent = 'UNLOCK WORKSTATION';
        }
      } catch (e) {
        err.textContent = 'Connection error. Try again.';
        err.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'UNLOCK WORKSTATION';
      }
    }

    document.getElementById('pin').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitAuth();
    });
  </script>
</body>
</html>`;
}

function getWaitingForTunnelHtml() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="5">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AGY // Waiting for Origin Bridge</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
    body { background: #030712; color: #fafafa; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; text-align: center; }
    .card { width: 100%; max-width: 440px; background: #090e1a; border: 1px solid rgba(0, 255, 204, 0.2); border-radius: 18px; padding: 36px 30px; }
    .spinner { width: 44px; height: 44px; border: 3px solid rgba(0, 255, 204, 0.1); border-top-color: #00ffcc; border-radius: 50%; animation: spin 1s infinite linear; margin: 0 auto 20px; }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    h2 { font-size: 20px; font-weight: 700; margin-bottom: 8px; color: #f8fafc; }
    p { font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 20px; }
    .code { background: #030712; border: 1px solid #1e293b; color: #00ffcc; padding: 8px 12px; border-radius: 6px; font-size: 12px; display: inline-block; }
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h2>Waiting for Device Bridge...</h2>
    <p>Your Edge Gateway is online, but no active origin tunnel has reported in yet.<br>Start the bridge on your computer or phone:</p>
    <div class="code">start.bat (Windows) &nbsp;|&nbsp; ./start.sh (Termux/Linux)</div>
    <p style="margin-top: 20px; font-size: 11px; color: #64748b;">This page auto-refreshes every 5 seconds.</p>
  </div>
</body>
</html>`;
}

function getTunnelErrorHtml(target, error) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AGY // Bridge Connection Error</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
    body { background: #030712; color: #fafafa; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; text-align: center; }
    .card { width: 100%; max-width: 440px; background: #090e1a; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 18px; padding: 36px 30px; }
    h2 { font-size: 20px; font-weight: 700; margin-bottom: 8px; color: #ef4444; }
    p { font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 16px; }
    .detail { background: #030712; border: 1px solid #1e293b; color: #f87171; padding: 10px; border-radius: 8px; font-size: 11px; text-align: left; word-break: break-all; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Origin Bridge Unreachable</h2>
    <p>The Edge Gateway could not communicate with the origin tunnel at:</p>
    <div class="detail">Target: ${target}<br>Error: ${error}</div>
    <p style="margin-top: 16px;"><a href="javascript:location.reload()" style="color: #00ffcc; text-decoration: none; font-weight: bold;">Retry Connection</a></p>
  </div>
</body>
</html>`;
}
