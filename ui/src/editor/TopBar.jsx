import { useEffect, useState } from 'react';
import { useStore } from '../store.js';

const ENGINE_LABELS = { gvhmr: 'GVHMR', mediapipe: 'MediaPipe' };

export default function TopBar() {
  const project = useStore((s) => s.project);
  const closeProject = useStore((s) => s.closeProject);
  const patchProject = useStore((s) => s.patchProject);
  const setInspectorTab = useStore((s) => s.setInspectorTab);
  const canUndo = useStore((s) => s.history.length > 0);
  const canRedo = useStore((s) => s.future.length > 0);
  const { undo, redo } = useStore.getState();
  const [dictName, setDictName] = useState(project?.dict_name || '');

  useEffect(() => setDictName(project?.dict_name || ''), [project?.dict_name]);

  const engine = project.settings.engine;
  const captured = project.captures[engine];

  return (
    <header className="topbar">
      <button className="ghost back" onClick={closeProject} title="Retour aux projets">
        ←
      </button>
      <div className="topbar-title">
        <strong title={project.name}>{project.name}</strong>
        <span className="muted">
          {project.frames} images · {project.fps.toFixed(0)} fps · {project.size[0]}×{project.size[1]}
        </span>
      </div>

      <label className="dict-field" title="Nom passé à RequestAnimDict / TaskPlayAnim">
        <span>Dictionnaire</span>
        <input
          className="text mono"
          value={dictName}
          onChange={(e) => setDictName(e.target.value)}
          onBlur={() => dictName !== project.dict_name && patchProject({ dict_name: dictName })}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        />
        <span className="muted">.ycd</span>
      </label>

      <div className="history-buttons">
        <button className="ghost" onClick={undo} disabled={!canUndo} title="Annuler (Ctrl+Z)">↶</button>
        <button className="ghost" onClick={redo} disabled={!canRedo} title="Rétablir (Ctrl+Y)">↷</button>
      </div>

      <span className={`engine-chip ${captured ? 'ok' : ''}`}>
        {ENGINE_LABELS[engine]} {captured ? '· analysé' : '· non analysé'}
      </span>
      <button className="primary" onClick={() => setInspectorTab('export')}>
        Exporter
      </button>
    </header>
  );
}
