import { useEffect, useRef, useState } from 'react';
import { api, waitForJob } from '../api.js';
import { useStore } from '../store.js';

const ENGINES = [
  {
    id: 'gvhmr',
    title: 'GVHMR',
    text: 'Meilleure qualité : rotations complètes, caméra mobile, sauts et déplacements. GPU requis.',
  },
  {
    id: 'mediapipe',
    title: 'MediaPipe',
    text: 'Rapide, licence libre. Corps sur place, rotation des membres approximative.',
  },
];

export default function CaptureGate() {
  const system = useStore((s) => s.system);
  const project = useStore((s) => s.project);
  const projectId = useStore((s) => s.projectId);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const following = useRef(false);

  const follow = async (started) => {
    if (following.current) return;
    following.current = true;
    setJob(started);
    try {
      await waitForJob(started.id, setJob);
      await useStore.getState().refreshProject();
      await useStore.getState().reloadMotion();
    } catch (e) {
      setError(e.message);
    } finally {
      following.current = false;
      setJob(null);
    }
  };

  useEffect(() => {
    const running = project.jobs?.find((j) => j.state === 'running' && j.kind.startsWith('capture'));
    if (running) follow(running);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const run = async (engine) => {
    setError(null);
    setJob({ progress: 0, message: 'Démarrage…' });
    try {
      await follow(await api.capture(projectId, engine));
    } catch (e) {
      setError(e.message);
      setJob(null);
    }
  };

  const switchEngine = (engine) => useStore.getState().patchProject({ settings: { ...project.settings, engine } });

  return (
    <div className="capture-gate">
      <div className="panel capture-card">
        <h2>Analyse du mouvement</h2>
        {job ? (
          <div className="progress-block">
            <div className="progress">
              <div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
            </div>
            <span>
              {Math.round((job.progress || 0) * 100)} % — {job.message || 'Démarrage…'}
            </span>
          </div>
        ) : (
          <div className="engines">
            {ENGINES.map((engine) => {
              const status = system?.engines[engine.id];
              const done = project.captures[engine.id];
              return (
                <div key={engine.id} className={`engine ${status?.ok ? '' : 'disabled'}`}>
                  <strong>{engine.title}</strong>
                  <p>{engine.text}</p>
                  {!status?.ok && <p className="error small">{status?.missing.join(' · ')}</p>}
                  {done ? (
                    <button className="secondary" onClick={() => switchEngine(engine.id)}>
                      Utiliser cette capture
                    </button>
                  ) : (
                    <button className="primary" disabled={!status?.ok} onClick={() => run(engine.id)}>
                      Analyser
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {error && <pre className="error small">{error}</pre>}
      </div>
    </div>
  );
}
