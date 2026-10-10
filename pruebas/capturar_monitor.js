// Abre /monitor en Edge (o Chrome) sin ventana y guarda una captura cada cierto tiempo mientras
// corre la prueba de carga. Requiere Node 22 o superior.
//
//   node pruebas/capturar_monitor.js --url http://127.0.0.1:8000/monitor --intervalo 10
//
// Cada captura se nombra con la fase que escribe prueba_carga.py (por ejemplo cola-n100_15-42-10.jpg).
// Se detiene con Ctrl+C.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const args = Object.fromEntries(process.argv.slice(2).reduce((pares, v, i, a) => (v.startsWith('--') ? [...pares, [v.slice(2), a[i + 1]]] : pares), []));
const URL_MONITOR = args.url || 'http://127.0.0.1:8000/monitor';
const INTERVALO = Number(args.intervalo || 10) * 1000;
const SALIDA = args.salida || path.join(__dirname, 'capturas');
const ARCHIVO_FASE = path.join(__dirname, 'resultados', 'fase_actual.txt');
const PUERTO = 9333;
const NAVEGADOR = process.env.NAVEGADOR || [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
].find(fs.existsSync);

const esperar = ms => new Promise(r => setTimeout(r, ms));
const fase = () => { try { return fs.readFileSync(ARCHIVO_FASE, 'utf8').trim() || 'inactivo'; } catch { return 'inactivo'; } };

async function main() {
  fs.mkdirSync(SALIDA, { recursive: true });
  const perfil = fs.mkdtempSync(path.join(os.tmpdir(), 'perfil-monitor-'));
  const navegador = spawn(NAVEGADOR, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${PUERTO}`, `--user-data-dir=${perfil}`, 'about:blank'], { stdio: 'ignore' });
  const cerrar = () => { navegador.kill(); process.exit(0); };
  process.on('SIGINT', cerrar);
  process.on('SIGTERM', cerrar);

  for (let i = 0; i < 50; i++) {
    try { await (await fetch(`http://127.0.0.1:${PUERTO}/json/version`)).json(); break; } catch { await esperar(200); }
  }
  const pestana = await (await fetch(`http://127.0.0.1:${PUERTO}/json/new?${encodeURIComponent(URL_MONITOR)}`, { method: 'PUT' })).json();
  const ws = new WebSocket(pestana.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let siguiente = 0;
  const pendientes = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (pendientes.has(m.id)) { pendientes.get(m.id)(m.result); pendientes.delete(m.id); }
  });
  const enviar = (method, params = {}) => new Promise(r => { const id = ++siguiente; pendientes.set(id, r); ws.send(JSON.stringify({ id, method, params })); });

  await enviar('Emulation.setDeviceMetricsOverride', { width: 1150, height: 790, deviceScaleFactor: 1.5, mobile: false });
  await esperar(3000);
  console.log(`Capturando ${URL_MONITOR} cada ${INTERVALO / 1000} s en ${SALIDA}`);

  while (true) {
    const { data } = await enviar('Page.captureScreenshot', { format: 'jpeg', quality: 85 });
    const hora = new Date().toTimeString().slice(0, 8).replaceAll(':', '-');
    const archivo = path.join(SALIDA, `${fase()}_${hora}.jpg`);
    fs.writeFileSync(archivo, Buffer.from(data, 'base64'));
    await esperar(INTERVALO);
  }
}

main().catch(e => { console.error(e); process.exit(1); });
