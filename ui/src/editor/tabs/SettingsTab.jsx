import { useState } from 'react';
import { api, waitForJob } from '../../api.js';
import { useStore } from '../../store.js';
import { Slider, Toggle } from '../fields.jsx';

const PEDS = [
  ['mp_m_freemode_01', 'Homme (mp_m_freemode_01)'],
  ['mp_f_freemode_01', 'Femme (mp_f_freemode_01)'],
];

export default function SettingsTab() {
  const project = useStore((s) => s.project);
  const projectId = useStore((s) => s.projectId);
  const system = useStore((s) => s.system);
  const { patchProject, refreshProject, reloadMotion } = useStore.getState();
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const settings = project.settings;
  const set = (changes) => patchProject({ settings: { ...settings, ...changes } });

  const recapture = async (engine) => {
    setError(null);
    try {
      const started = await api.capture(projectId, engine);
      setJob(started);
      await waitForJob(started.id, setJob);
      await refreshProject();
      await reloadMotion();
    } catch (e) {
      setError(e.message);
    } finally {
      setJob(null);
    }
  };

  return (
    <div className="stack">
      <span className="group-title">Moteur d'extraction</span>
      {['gvhmr', 'mediapipe'].map((engine) => {
        const ok = system?.engines[engine].ok;
        const done = project.captures[engine];
        return (
          <div key={engine} className={`engine-row ${settings.engine === engine ? 'active' : ''}`}>
            <label>
              <input type="radio" name="engine" checked={settings.engine === engine} disabled={!done} onChange={() => set({ engine })} />
              <strong>{engine === 'gvhmr' ? 'GVHMR' : 'MediaPipe'}</strong>
              <span className="muted small">{done ? 'capturé' : ok ? 'non capturé' : 'indisponible'}</span>
            </label>
            <button className="secondary small" disabled={!ok || !!job} onClick={() => recapture(engine)}>
              {done ? 'Relancer' : 'Analyser'}
            </button>
          </div>
        );
      })}
      {job && (
        <div className="progress-block">
          <div className="progress"><div style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
          <span className="small">{job.message}</span>
        </div>
      )}
      {error && <pre className="error small">{error}</pre>}

      <label className="field">
        Ped cible
        <select value={settings.ped} onChange={(e) => set({ ped: e.target.value })}>
          {PEDS.map(([id, text]) => (
            <option key={id} value={id}>{text}</option>
          ))}
        </select>
      </label>

      {settings.engine === 'gvhmr' ? (
        <Toggle label="Redresser la verticale" checked={settings.upright_gvhmr} onChange={(upright_gvhmr) => set({ upright_gvhmr })} hint="GVHMR estime déjà la gravité : à n'activer que si tout le corps penche visiblement dans une vidéo où la personne se tient surtout droite. Sur un clip court de course ou d'esquive, cela fait basculer le sol." />
      ) : (
        <Toggle label="Redresser la verticale" checked={settings.upright} onChange={(upright) => set({ upright })} hint="MediaPipe suit les axes de la caméra : compense une prise de vue en plongée ou inclinée, en supposant le corps droit en moyenne." />
      )}
      {settings.engine === 'gvhmr' && (
        <Toggle label="Placer les mains (contact avec le corps)" checked={settings.hand_placement} onChange={(hand_placement) => set({ hand_placement })} hint="Le torse des peds GTA est ~30 % plus haut qu'un humain moyen : en copiant seulement les angles, une main posée sur la hanche remonte au ventre. Cette option replace chaque main là où elle est dans la vidéo, par rapport au corps." />
      )}
      <Slider label="Lissage des rotations" value={settings.smoothing} min={0} max={4} step={0.25} format={(v) => (v ? v.toFixed(2) : 'aucun')} onCommit={(smoothing) => set({ smoothing })} />
      <Slider label="Lissage du bassin" value={settings.root_smoothing} min={0} max={6} step={0.25} format={(v) => (v ? v.toFixed(2) : 'aucun')} onCommit={(root_smoothing) => set({ root_smoothing })} />
      {settings.engine === 'mediapipe' && (
        <Slider label="Inclinaison de la tête" value={settings.head_pitch} min={-30} max={40} step={1} format={(v) => `${v}°`} onCommit={(head_pitch) => set({ head_pitch })} />
      )}
      {settings.engine === 'gvhmr' && (
        <label className="field">
          Hauteur du corps
          <span className="muted small">Réglable aussi clip par clip (onglet Clips) : pieds au sol pour les courses, Auto pour les sauts.</span>
          <select value={settings.ground} onChange={(e) => set({ ground: e.target.value })}>
            <option value="planted">Pieds toujours au sol (recommandé)</option>
            <option value="auto">Auto : pieds au sol, sauts conservés</option>
            <option value="tracked">Suivie brute (peut flotter)</option>
          </select>
        </label>
      )}
    </div>
  );
}
