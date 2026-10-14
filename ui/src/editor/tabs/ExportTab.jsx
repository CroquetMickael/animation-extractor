import { useState } from 'react';
import { api, waitForJob } from '../../api.js';
import { useStore } from '../../store.js';

const STREAM_KEY = 'animx.streamDir';

function readStreamDir() {
  try {
    return localStorage.getItem(STREAM_KEY) || '';
  } catch {
    return '';
  }
}

export default function ExportTab() {
  const project = useStore((s) => s.project);
  const projectId = useStore((s) => s.projectId);
  const [job, setJob] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [error, setError] = useState(null);
  const [streamDir, setStreamDir] = useState(readStreamDir);
  const [installed, setInstalled] = useState(null);
  const [lang, setLang] = useState('lua');

  const run = async () => {
    setError(null);
    setInstalled(null);
    try {
      const started = await api.exportProject(projectId);
      setJob(started);
      const done = await waitForJob(started.id, setJob);
      setManifest(done.result);
    } catch (e) {
      setError(e.message);
    } finally {
      setJob(null);
    }
  };

  const install = async () => {
    setError(null);
    try {
      localStorage.setItem(STREAM_KEY, streamDir);
    } catch {
      // storage unavailable, keep going
    }
    try {
      const result = await api.install(projectId, streamDir);
      setInstalled(result.path);
    } catch (e) {
      setError(e.message);
    }
  };

  const dict = project.dict_name;
  const firstClip = project.clips[0];
  const snippet = lang === 'lua' ? luaSnippet(dict, firstClip) : jsSnippet(dict, firstClip);

  return (
    <div className="stack">
      <button className="primary big" onClick={run} disabled={!!job}>
        {job ? 'Compilation…' : `Compiler ${dict}.ycd`}
      </button>
      {job && (
        <div className="progress-block">
          <div className="progress"><div style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
          <span className="small">{job.message}</span>
        </div>
      )}
      {error && <pre className="error small">{error}</pre>}

      {manifest && (
        <div className="export-result">
          <span className="ok-text">✓ {manifest.bridge}</span>
          <table>
            <tbody>
              {manifest.clips.map((c) => (
                <tr key={c.name}>
                  <td className="mono">{c.name}</td>
                  <td>{c.frames} img</td>
                  <td>{c.duration.toFixed(2)} s</td>
                  <td>{c.loop ? 'boucle' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <a className="secondary button" href={api.downloadUrl(projectId)} download>
            Télécharger {dict}.ycd
          </a>
          <label className="field">
            Dossier stream d'une ressource FiveM
            <input className="text mono" placeholder="…\resources\[anims]\mes_anims\stream" value={streamDir} onChange={(e) => setStreamDir(e.target.value)} />
          </label>
          <button className="secondary" onClick={install} disabled={!streamDir}>
            Copier dans la ressource
          </button>
          {installed && <span className="ok-text small">Copié : {installed}</span>}
        </div>
      )}

      <div className="snippet">
        <div className="segmented small">
          <button className={lang === 'lua' ? 'active' : ''} onClick={() => setLang('lua')}>Lua</button>
          <button className={lang === 'js' ? 'active' : ''} onClick={() => setLang('js')}>JS</button>
        </div>
        <pre className="mono">{snippet}</pre>
        <p className="muted small">
          Les deux premiers nombres règlent le fondu d'entrée et de sortie : 8.0 ≈ 0,12 s (sec), 4.0 ≈ 0,25 s, 2.0 ≈ 0,5 s. Baisse-les si le passage depuis la course est trop brutal.
        </p>
        <p className="muted small">
          Un .ycd placé dans le dossier <code>stream/</code> d'une ressource est streamé automatiquement, sans ligne à ajouter dans le fxmanifest.
        </p>
      </div>
    </div>
  );
}

function luaSnippet(dict, clip) {
  const flag = clip?.loop ? 1 : 0;
  return `RequestAnimDict("${dict}")
while not HasAnimDictLoaded("${dict}") do Wait(0) end
TaskPlayAnim(PlayerPedId(), "${dict}", "${clip?.name}", 4.0, -4.0, -1, ${flag}, 0.0, false, false, false)`;
}

function jsSnippet(dict, clip) {
  const flag = clip?.loop ? 1 : 0;
  return `RequestAnimDict('${dict}');
while (!HasAnimDictLoaded('${dict}')) await new Promise((r) => setTimeout(r, 0));
TaskPlayAnim(PlayerPedId(), '${dict}', '${clip?.name}', 4.0, -4.0, -1, ${flag}, 0.0, false, false, false);`;
}
