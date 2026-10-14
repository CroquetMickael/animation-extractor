import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { useStore } from '../store.js';

export default function Home() {
  const system = useStore((s) => s.system);
  const openProject = useStore((s) => s.openProject);
  const [projects, setProjects] = useState([]);
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const input = useRef(null);

  const refresh = () => api.projects().then(setProjects).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
  }, []);

  const pick = (picked) => {
    if (!picked) return;
    setFile(picked);
    if (!name) setName(picked.name.replace(/\.[^.]+$/, ''));
  };

  const create = async () => {
    if (!file || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject(file, name.trim());
      await openProject(project.id);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  const remove = async (event, id) => {
    event.stopPropagation();
    if (!window.confirm('Supprimer ce projet et ses captures ?')) return;
    // Release the preview stream first, otherwise Windows keeps the video file locked.
    const preview = event.currentTarget.closest('.project-card')?.querySelector('video');
    if (preview) {
      preview.removeAttribute('src');
      preview.load();
    }
    try {
      await api.deleteProject(id);
    } catch (e) {
      setError(e.message);
    }
    refresh();
  };

  return (
    <div className="home">
      <header className="home-header">
        <div className="brand">
          <span className="brand-mark">AX</span>
          <div>
            <h1>Anim Extract</h1>
            <p>Vidéo → animation GTA V / FiveM (.ycd)</p>
          </div>
        </div>
        <SystemBadges system={system} />
      </header>

      <section className="panel new-project">
        <h2>Nouveau projet</h2>
        <div
          className={`dropzone ${dragOver ? 'over' : ''} ${file ? 'has-file' : ''}`}
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            pick(e.dataTransfer.files?.[0]);
          }}
        >
          <input ref={input} type="file" accept="video/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span>{(file.size / 1024 / 1024).toFixed(1)} Mo — cliquer pour changer</span>
            </>
          ) : (
            <>
              <strong>Déposer une vidéo ici</strong>
              <span>ou cliquer pour parcourir (mp4, mov, webm…)</span>
            </>
          )}
        </div>
        <div className="row">
          <input className="text" placeholder="Nom du projet" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="primary" disabled={!file || !name.trim() || busy} onClick={create}>
            {busy ? 'Import…' : 'Créer'}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </section>

      <section className="panel">
        <h2>Projets</h2>
        {projects.length === 0 && <p className="muted">Aucun projet pour l'instant.</p>}
        <div className="project-grid">
          {projects.map((p) => (
            <button key={p.id} className="project-card" onClick={() => openProject(p.id)}>
              <video src={`${api.videoUrl(p.id)}#t=1`} muted preload="metadata" />
              <div className="project-meta">
                <strong>{p.name}</strong>
                <span>
                  {p.clips.length} clip{p.clips.length > 1 ? 's' : ''} · {p.dict_name}.ycd
                </span>
                <span className="tags">
                  {Object.entries(p.captures)
                    .filter(([, ok]) => ok)
                    .map(([engine]) => (
                      <em key={engine}>{engine}</em>
                    ))}
                </span>
              </div>
              <span className="delete" onClick={(e) => remove(e, p.id)} title="Supprimer">
                ✕
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function SystemBadges({ system }) {
  if (!system) return null;
  const items = [
    ['GTA V', system.gta_ok],
    ['Bridge', system.bridge_ok],
    [system.gpu || 'GPU', !!system.gpu],
    ['MediaPipe', system.engines.mediapipe.ok],
    ['GVHMR', system.engines.gvhmr.ok],
  ];
  return (
    <div className="badges">
      {items.map(([label, ok]) => (
        <span key={label} className={`badge ${ok ? 'ok' : 'ko'}`} title={label === 'GVHMR' && !ok ? system.engines.gvhmr.missing.join('\n') : ''}>
          {label}
        </span>
      ))}
    </div>
  );
}
