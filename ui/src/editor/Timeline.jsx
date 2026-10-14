import { useEffect, useState } from 'react';
import { FULL, useStore } from '../store.js';
import CutDetector from './CutDetector.jsx';
import TimelineTracks from './TimelineTracks.jsx';

export { CLIP_COLORS } from './TimelineTracks.jsx';

export default function Timeline() {
  const project = useStore((s) => s.project);
  const clipId = useStore((s) => s.clipId);
  const motion = useStore((s) => s.motion);
  const playing = useStore((s) => s.playing);
  // Re-render on every frame: the time readout and the tool targets follow the play head.
  useStore((s) => s.frame);
  const store = useStore.getState();
  const [selectedKey, setSelectedKey] = useState(null);
  const [message, setMessage] = useState(null);
  const [detector, setDetector] = useState(false);
  const [candidates, setCandidates] = useState([]);

  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(() => setMessage(null), 3500);
    return () => clearTimeout(timer);
  }, [message]);

  const run = async (action) => {
    store.setPlaying(false);
    const error = await action();
    if (error) setMessage(error);
  };

  useCutShortcuts(run, setDetector);
  useKeyDeletion(selectedKey, setSelectedKey);

  // A key index only means something inside the clip it was picked in.
  useEffect(() => setSelectedKey(null), [clipId]);

  if (!project) return null;
  const full = clipId === FULL;
  const clip = full ? null : project.clips.find((c) => c.id === clipId);
  const target = store.targetClip();
  const playheadSource = store.sourceFrame();
  const sortedClips = [...project.clips].sort((a, b) => a.start - b.start);

  const hasNext = target && sortedClips.findIndex((c) => c.id === target.id) < sortedClips.length - 1;

  return (
    <footer className="timeline">
      <div className="timeline-toolbar">
        <button className="primary round" onClick={() => store.setPlaying(!playing)} disabled={!motion} title="Lecture / pause (Espace)">
          {playing ? '❚❚' : '▶'}
        </button>
        <span className="mono time">
          {(playheadSource / project.fps).toFixed(2)} s · img {Math.round(playheadSource)}
        </span>
        <span className={`mode-chip ${full ? 'full' : ''}`}>{full ? 'Vidéo entière' : clip?.name}</span>
        <div className="tool-group">
          <button className="tool" onClick={() => run(store.splitAtPlayhead)} disabled={!target} title="Couper le clip à la tête de lecture (C)">
            ✂ Couper
          </button>
          <button className="tool" onClick={() => run(() => store.setClipBound('start'))} disabled={!target} title="Début du clip ici (I)">
            [ Début
          </button>
          <button className="tool" onClick={() => run(() => store.setClipBound('end'))} disabled={!target} title="Fin du clip ici (O)">
            Fin ]
          </button>
          <button className="tool" onClick={() => run(store.newClipAtPlayhead)} title="Nouveau clip à partir d'ici (N)">
            + Clip ici
          </button>
          <button className="tool" onClick={() => run(() => store.mergeNext(target.id))} disabled={!hasNext} title="Fusionner avec le clip suivant">
            Fusionner →
          </button>
          <button className={`tool ${detector ? 'on' : ''}`} onClick={() => setDetector(!detector)} title="Détecter les changements d'animation (D)">
            ✦ Détection auto
          </button>
        </div>
        {target && !full && <span className="muted small">{((target.end - target.start) / project.fps).toFixed(2)} s</span>}
        {full && target && <span className="muted small">sur : {target.name}</span>}
        {message && <span className="toast">{message}</span>}
      </div>

      {detector && <CutDetector onClose={() => setDetector(false)} onCandidates={setCandidates} />}

      <TimelineTracks candidates={candidates} showCandidates={detector} selectedKey={selectedKey} setSelectedKey={setSelectedKey} KeyPopover={KeyPopover} />
    </footer>
  );
}

function useCutShortcuts(run, setDetector) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.target.closest('input, textarea, select') || event.ctrlKey || event.altKey || event.metaKey) return;
      const store = useStore.getState();
      const actions = {
        KeyC: () => run(store.splitAtPlayhead),
        KeyI: () => run(() => store.setClipBound('start')),
        KeyO: () => run(() => store.setClipBound('end')),
        KeyN: () => run(store.newClipAtPlayhead),
        KeyD: () => setDetector((open) => !open),
      };
      const action = actions[event.code];
      if (!action) return;
      event.preventDefault();
      action();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [run, setDetector]);
}

function KeyPopover({ keyData, left, onDelete, onClose }) {
  const span = keyData.radius < 0 ? 'tout le clip' : keyData.radius === 0 ? 'cette image' : `±${keyData.radius} images`;
  return (
    <div className="key-popover" style={{ left: `${left}%` }} onPointerDown={(e) => e.stopPropagation()}>
      <div className="key-popover-info">
        <strong className="mono">{keyData.bone.replace('SKEL_', '')}</strong>
        <span className="muted">image {keyData.frame} · {span}</span>
      </div>
      <button className="danger small" onClick={onDelete} title="Supprimer cette correction (Suppr)">
        Supprimer
      </button>
      <button className="icon" onClick={onClose} title="Fermer">
        ✕
      </button>
    </div>
  );
}

function useKeyDeletion(selectedKey, setSelectedKey) {
  useEffect(() => {
    if (selectedKey === null) return undefined;
    const onKey = (event) => {
      if (event.target.closest('input, textarea, select')) return;
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        useStore.getState().removeKey(selectedKey);
        setSelectedKey(null);
      } else if (event.key === 'Escape') {
        setSelectedKey(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedKey, setSelectedKey]);
}
