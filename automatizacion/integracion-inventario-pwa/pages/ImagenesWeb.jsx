import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

// Pantalla "Imágenes web" para la Inventario PWA.
// Reproduce el flujo de automatizacion/pwa (subir frente+trasero, cascada
// Tipo → Categoría → Marca → Referencia, botón Generar) pero llamando al
// backend FastAPI a través de nginx en /img-api/ (reverse proxy a
// http://127.0.0.1:8080/api/). El 8080 NO se expone al exterior.
//
// Estos endpoints son públicos (no usan el token del inventario), por eso se
// llaman con fetch directo y NO con el cliente de lib/api.js.
const IMG_API = '/img-api';

async function getJSON(path) {
  const r = await fetch(`${IMG_API}${path}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export default function ImagenesWeb() {
  const nav = useNavigate();

  const [tipos, setTipos] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [marcas, setMarcas] = useState([]);
  const [referencias, setReferencias] = useState([]);

  const [tipo, setTipo] = useState('');
  const [categoria, setCategoria] = useState('');
  const [marca, setMarca] = useState('');
  const [referencia, setReferencia] = useState('');

  const [frente, setFrente] = useState(null);
  const [trasero, setTrasero] = useState(null);
  const [frentePrev, setFrentePrev] = useState('');
  const [traseroPrev, setTraseroPrev] = useState('');

  const [busy, setBusy] = useState(false);
  const [estado, setEstado] = useState(null); // { tipo: 'accent'|'danger'|'warn', msg }

  // Catálogos iniciales
  useEffect(() => {
    getJSON('/tipos').then(setTipos)
      .catch(() => setEstado({ tipo: 'danger', msg: 'No se pudieron cargar los tipos de prenda.' }));
    getJSON('/categories').then(setCategorias).catch(() => {});
  }, []);

  // Cascada categoría -> marca
  function onCategoria(id) {
    setCategoria(id);
    setMarca(''); setMarcas([]);
    setReferencia(''); setReferencias([]);
    if (!id) return;
    getJSON(`/brands?category_id=${id}`).then(setMarcas).catch(() => {});
  }

  // Cascada marca -> referencia
  function onMarca(b) {
    setMarca(b);
    setReferencia(''); setReferencias([]);
    if (!b) return;
    getJSON(`/references?category_id=${categoria}&brand=${encodeURIComponent(b)}`)
      .then(setReferencias).catch(() => {});
  }

  function onFile(file, setFile, setPrev) {
    setFile(file || null);
    setPrev(file ? URL.createObjectURL(file) : '');
  }

  const refObj = referencias.find(r => String(r.id) === String(referencia));
  const puedeGenerar = tipo && categoria && marca && referencia && frente && trasero && !busy;

  async function generar() {
    if (!puedeGenerar) return;
    setBusy(true);
    setEstado({ tipo: 'accent', msg: 'Generando imágenes… esto puede tardar hasta un minuto.' });
    try {
      const fd = new FormData();
      fd.append('reference_id', referencia);
      fd.append('tipo', tipo);
      fd.append('descripcion', refObj?.name || '');
      fd.append('frente', frente);
      fd.append('trasero', trasero);
      const r = await fetch(`${IMG_API}/jobs`, { method: 'POST', body: fd });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      setEstado({
        tipo: 'accent',
        msg: `✅ Listo: ${data.imagenes} imagen(es) subida(s) al producto. ` +
             'Etiquetas "Revisión de imágenes" y "Listo" añadidas en Odoo.',
      });
    } catch (err) {
      setEstado({ tipo: 'danger', msg: '❌ ' + (err.message || 'Error generando imágenes.') });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <div className="app-header">
        <div className="left">
          <button onClick={() => nav('/')} style={{ fontSize: 20, color: 'var(--text-muted)' }}>←</button>
          <h1>Imágenes web</h1>
        </div>
      </div>

      <div className="app-content">
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 0 }}>
          Sube la foto de frente y de espalda de la prenda, elige el producto y genera las
          imágenes para la web.
        </p>

        <div className="section-label">Fotos (obligatorias)</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}>
          <FotoInput label="Frente" prev={frentePrev} onPick={(f) => onFile(f, setFrente, setFrentePrev)} />
          <FotoInput label="Espalda" prev={traseroPrev} onPick={(f) => onFile(f, setTrasero, setTraseroPrev)} />
        </div>

        <div className="section-label">Producto</div>
        <div className="field">
          <label>Tipo de prenda</label>
          <select className="select" value={tipo} onChange={e => setTipo(e.target.value)}>
            <option value="">Elige tipo…</option>
            {tipos.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Categoría</label>
          <select className="select" value={categoria} onChange={e => onCategoria(e.target.value)}>
            <option value="">Elige categoría…</option>
            {categorias.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Marca</label>
          <select className="select" value={marca} disabled={!categoria || marcas.length === 0}
                  onChange={e => onMarca(e.target.value)}>
            <option value="">{categoria ? 'Elige marca…' : 'Elige categoría primero'}</option>
            {marcas.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label>Referencia</label>
          <select className="select" value={referencia} disabled={!marca || referencias.length === 0}
                  onChange={e => setReferencia(e.target.value)}>
            <option value="">{marca ? 'Elige referencia…' : 'Elige marca primero'}</option>
            {referencias.map(r => (
              <option key={r.id} value={r.id}>
                {r.default_code ? `${r.default_code} · ${r.name}` : r.name}
              </option>
            ))}
          </select>
        </div>

        {estado && (
          <div className={`banner ${estado.tipo}`} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {busy && <span className="spinner" />}
            <span>{estado.msg}</span>
          </div>
        )}

        <button className="btn primary full lg" disabled={!puedeGenerar} onClick={generar}
                style={{ marginTop: 8 }}>
          {busy ? 'Generando…' : 'Generar imágenes'}
        </button>
      </div>
    </div>
  );
}

function FotoInput({ label, prev, onPick }) {
  return (
    <label style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      gap: 6, height: 150, border: '0.5px dashed var(--border-strong)', borderRadius: 'var(--radius-md)',
      background: 'var(--bg-2)', cursor: 'pointer', overflow: 'hidden', position: 'relative',
    }}>
      {prev
        ? <img src={prev} alt={label}
               style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
        : (
          <>
            <span style={{ fontSize: 26 }}>📷</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
          </>
        )}
      <input type="file" accept="image/*" capture="environment" style={{ display: 'none' }}
             onChange={e => onPick(e.target.files[0])} />
    </label>
  );
}
