import { useEffect, useState } from 'react';
import { api, waitForJob } from '../../api.js';
import { useStore } from '../../store.js';
import { CommitInput } from '../fields.jsx';

const SLOTS = [
  ['idle', 'Arrêt (idle)', 'en boucle, sur place'],
  ['walk', 'Marche', 'boucle sur des foulées entières'],
  ['run', 'Course', 'boucle sur des foulées entières'],
  ['sprint', 'Sprint', 'boucle sur des foulées entières'],
];
const RESOURCES_KEY = 'animx.resourcesDir';

function readResourcesDir() {
  try {
    return localStorage.getItem(RESOURCES_KEY) || '';
  } catch {
    return '';
  }
}

export default function MovesetTab() {
  const project = useStore((s) => s.project);
  const projectId = useStore((s) => s.projectId);
  const patchProject = useStore((s) => s.patchProject);
  const movesets = project.movesets || [];
  const [currentId, setCurrentId] = useState(movesets[0]?.id ?? null);
  const [suggestions, setSuggestions] = useState(null);
  const [defaults, setDefaults] = useState({});
  const [fallback, setFallback] = useState('');
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [resourcesDir, setResourcesDir] = useState(readResourcesDir);
  const [installed, setInstalled] = useState(null);
  const [previewClips, setPreviewClips] = useState([]);
  const preview = useStore((s) => s.preview);
  const previewMoveset = useStore((s) => s.previewMoveset);
  const motionLoading = useStore((s) => s.motionLoading);
  const current = movesets.find((m) => m.id === currentId) || movesets[0];
  const slotsKey = JSON.stringify(current?.slots || {});

  useEffect(() => {
    if (!current) {
      setPreviewClips([]);
      return;
    }
    api.movesetPreviewClips(projectId, current.id).then((data) => setPreviewClips(data.clips)).catch(() => setPreviewClips([]));
  }, [projectId, current?.id, slotsKey]);

  // Leaving the tab puts the edited clip back in the viewer.
  useEffect(() => () => {
    if (useStore.getState().preview) useStore.getState().reloadMotion();
  }, []);

  useEffect(() => {
    api
      .suggestMoveset(projectId)
      .then((data) => {
        setSuggestions(data.suggestions);
        setDefaults(data.defaults);
        setFallback(data.fallback);
      })
      .catch((e) => setError(e.message));
  }, [projectId, project.clips.length, project.settings.engine]);

  const save = (next) => patchProject({ movesets: next });
  const update = (changes) => save(movesets.map((m) => (m.id === current.id ? { ...m, ...changes } : m)));

  const create = async () => {
    const name = `${project.dict_name}_move`.replace(/_+/g, '_');
    await save([...movesets, { name, dict: `${name}@clips`, slots: {}, speeds: {} }]);
    const created = useStore.getState().project.movesets?.at(-1);
    if (created) setCurrentId(created.id);
  };

  const autoAssign = () => {
    if (!suggestions) return;
    const slots = {};
    for (const [slot] of SLOTS) {
      const candidates = suggestions.filter((s) => s.slot === slot);
      // Prefer the most regular gait for locomotion slots, the longest calm clip for idle.
      const best = candidates.sort((a, b) => (b.analysis?.periodicity || 0) - (a.analysis?.periodicity || 0))[0];
      if (best) slots[slot] = best.clip;
    }
    update({ slots });
  };

  const exportMoveset = async () => {
    setError(null);
    setResult(null);
    setInstalled(null);
    try {
      const started = await api.exportMoveset(projectId, current.id);
      setJob(started);
      const done = await waitForJob(started.id, setJob);
      setResult(done.result);
    } catch (e) {
      setError(e.message);
    } finally {
      setJob(null);
    }
  };

  const install = async () => {
    setError(null);
    try {
      localStorage.setItem(RESOURCES_KEY, resourcesDir);
    } catch {
      // storage unavailable, keep going
    }
    try {
      const response = await api.installMoveset(projectId, current.id, resourcesDir);
      setInstalled(response.path);
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Supprimer le style ${current.name} ?`)) return;
    await save(movesets.filter((m) => m.id !== current.id));
    setCurrentId(null);
  };

  const suggestionFor = (clipId) => suggestions?.find((s) => s.clip === clipId);

  return (
    <div className="stack">
      <p className="muted small">
        Un style de déplacement remplace l'arrêt, la marche, la course et le sprint du ped. GTA enchaîne lui-même les transitions ; démarrages, arrêts, virages et pentes viennent du style par défaut
        {fallback ? <> (<code>{fallback}</code>)</> : null}.
      </p>

      <div className="row">
        <select value={current?.id || ''} onChange={(e) => setCurrentId(e.target.value)} disabled={!movesets.length}>
          {movesets.length === 0 && <option value="">Aucun style</option>}
          {movesets.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
        <button className="secondary" onClick={create}>+ Nouveau</button>
      </div>

      {current && (
        <>
          <label className="field">
            Nom du style (SetPedMovementClipset)
            <CommitInput className="text mono" value={current.name} onCommit={(name) => update({ name })} />
          </label>
          <label className="field">
            Dictionnaire d'animations
            <CommitInput className="text mono" value={current.dict || ''} onCommit={(dict) => update({ dict })} />
          </label>

          <div className="slot-head">
            <span className="group-title">Clips du style</span>
            <button className="secondary small" onClick={autoAssign} disabled={!suggestions} title="Attribue chaque rôle au clip dont l'allure détectée correspond">
              ✦ Attribution auto
            </button>
          </div>
          {SLOTS.map(([slot, label, hint]) => {
            const clipId = current.slots?.[slot] || '';
            const suggestion = clipId ? suggestionFor(clipId) : null;
            const mismatch = suggestion && suggestion.slot !== slot;
            return (
              <div key={slot} className="slot-row">
                <label className="field">
                  {label} <span className="muted">· {hint}</span>
                  <select value={clipId} onChange={(e) => update({ slots: { ...current.slots, [slot]: e.target.value || undefined } })}>
                    <option value="">— style par défaut —</option>
                    {project.clips.map((c) => {
                      const s = suggestionFor(c.id);
                      const tag = s?.analysis ? ` · ${s.analysis.gait} ${s.analysis.cadence.toFixed(1)} pas/s` : s ? ' · sans rythme' : '';
                      return (
                        <option key={c.id} value={c.id}>{c.name}{tag}</option>
                      );
                    })}
                  </select>
                </label>
                {slot !== 'idle' && clipId && (
                  <label className="field speed-field">
                    Vitesse
                    <CommitInput
                      type="number"
                      step="0.1"
                      min="0.5"
                      max="10"
                      value={current.speeds?.[slot] ?? defaults[slot] ?? ''}
                      onCommit={(v) => update({ speeds: { ...current.speeds, [slot]: v } })}
                    />
                  </label>
                )}
                {mismatch && (
                  <p className="warn small">
                    Ce clip ressemble plutôt à « {SLOTS.find(([id]) => id === suggestion.slot)?.[1] || suggestion.slot} ».
                  </p>
                )}
              </div>
            );
          })}
          <p className="muted small">
            Vitesses par défaut = celles de Rockstar (marche {defaults.walk}, course {defaults.run}, sprint {defaults.sprint} m/s) : ton ped garde la même vitesse de jeu qu'avec le style normal.
          </p>

          {previewClips.length > 0 && (
            <div className="stack">
              <span className="group-title">Aperçu en jeu</span>
              <p className="muted small">Joue dans la vue 3D ce que GTA recevra, le ped suivant sa trajectoire. « Parcours complet » enchaîne tout le style : arrêt, démarrage, marche, course, virages, sprint, arrêt.</p>
              <div className="row wrap">
                {previewClips.map((name) => (
                  <button
                    key={name}
                    className={preview?.moveset === current.id && preview?.clip === name ? 'primary small' : 'secondary small'}
                    onClick={() => previewMoveset(current.id, name)}
                    disabled={motionLoading}
                  >
                    {name === 'parcours' ? '▶ Parcours complet' : name}
                  </button>
                ))}
              </div>
              {preview?.moveset === current.id && (
                <button className="secondary small" onClick={() => useStore.getState().reloadMotion()}>Revenir au clip édité</button>
              )}
            </div>
          )}

          <div className="row">
            <button className="primary" onClick={exportMoveset} disabled={!!job || !Object.values(current.slots || {}).some(Boolean)}>
              {job ? 'Génération…' : 'Générer la ressource'}
            </button>
            <button className="danger" onClick={remove}>Supprimer</button>
          </div>
          {job && (
            <div className="progress-block">
              <div className="progress"><div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></div>
              <span className="small">{job.message}</span>
            </div>
          )}
          {error && <pre className="error small">{error}</pre>}

          {result && (
            <div className="export-result">
              <span className="ok-text">✓ {result.bridge} · repli {result.fallback}</span>
              <table>
                <tbody>
                  {result.slots.map((s) => (
                    <tr key={s.slot}>
                      <td className="mono">{s.slot}</td>
                      <td>{s.duration.toFixed(2)} s</td>
                      <td>{s.slot === 'idle' ? 'boucle' : s.aligned ? `${s.strides} foulée${s.strides > 1 ? 's' : ''}` : 'boucle par fondu'}</td>
                      <td>{s.speed ? `${s.speed.toFixed(2)} m/s` : ''}</td>
                      <td title={(s.turns || []).join(', ')}>{s.turns?.length ? `+ ${s.turns.length} virages` : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small" title={(result.transitions || []).join(', ')}>
                {result.transitions?.length
                  ? `+ ${result.transitions.length} transitions (démarrages, arrêts, changements d'allure)`
                  : "Pas de transition : il faut l'arrêt avec la marche ou la course pour les démarrages et arrêts, et la marche avec la course pour les changements d'allure."}
              </p>
              {result.slots.some((s) => s.slot !== 'idle' && !s.aligned) && (
                <p className="warn small">Moins de deux foulées complètes détectées sur certains clips : la boucle est faite par fondu, des pas peuvent glisser. Un clip plus long de course régulière donnera une boucle propre.</p>
              )}
              <p className="muted small mono">{result.folder}</p>
              <a className="secondary button" href={api.movesetDownloadUrl(projectId, current.id)} download>
                Télécharger {result.clipset}.zip
              </a>
              <label className="field">
                Dossier resources de ton serveur
                <input className="text mono" placeholder="…\server-data\resources\[anims]" value={resourcesDir} onChange={(e) => setResourcesDir(e.target.value)} />
              </label>
              <button className="secondary" onClick={install} disabled={!resourcesDir}>Copier la ressource</button>
              {installed && <span className="ok-text small">Copiée : {installed} — ajoute « ensure {current.name} »</span>}
              <pre className="mono snippet-block">{`RequestAnimSet('${current.name}')
while not HasAnimSetLoaded('${current.name}') do Wait(0) end
SetPedMovementClipset(PlayerPedId(), '${current.name}', 0.25)
-- retour au style normal :
ResetPedMovementClipset(PlayerPedId(), 0.25)`}</pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}
