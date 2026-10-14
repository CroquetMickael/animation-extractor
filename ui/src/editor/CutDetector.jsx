import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { useStore } from '../store.js';

export default function CutDetector({ onClose, onCandidates }) {
  const projectId = useStore((s) => s.projectId);
  const project = useStore((s) => s.project);
  const [candidates, setCandidates] = useState(null);
  const [threshold, setThreshold] = useState(0.5);
  const [replace, setReplace] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.cutCandidates(projectId)
      .then((data) => setCandidates(data.candidates))
      .catch((e) => setError(e.message));
  }, [projectId, project.settings.engine]);

  const selected = useMemo(() => (candidates || []).filter((c) => c.score >= threshold), [candidates, threshold]);

  useEffect(() => {
    onCandidates((candidates || []).map((c) => ({ ...c, on: c.score >= threshold })));
    return () => onCandidates([]);
  }, [candidates, threshold, onCandidates]);

  const apply = async () => {
    if (replace && project.clips.length > 1 && !window.confirm(`Remplacer les ${project.clips.length} clips actuels par ${selected.length + 1} clips ?`)) return;
    setBusy(true);
    await useStore.getState().applyCuts(selected.map((c) => c.frame).sort((a, b) => a - b), replace);
    setBusy(false);
    onClose();
  };

  return (
    <div className="cut-detector">
      <strong>Détection des changements d'animation</strong>
      {error && <span className="error small">{error}</span>}
      {!candidates && !error && <span className="muted small">Analyse…</span>}
      {candidates && (
        <>
          <label className="slider-row inline">
            <span>
              Sensibilité <em>{selected.length + 1} clips</em>
            </span>
            <input type="range" min={0.05} max={1} step={0.01} value={1.05 - threshold} onChange={(e) => setThreshold(1.05 - Number(e.target.value))} />
          </label>
          <label className="check">
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Remplacer les clips existants
          </label>
          <button className="primary" onClick={apply} disabled={busy}>
            Créer {selected.length + 1} clips
          </button>
          <button className="ghost" onClick={onClose}>Fermer</button>
        </>
      )}
    </div>
  );
}
