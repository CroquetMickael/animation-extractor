import { useState } from 'react';
import { FULL, useStore } from '../store.js';

export const CLIP_COLORS = ['#ffac00', '#4fd1ff', '#9b7bff', '#5ee08f', '#ff6b8b', '#ffd24f'];

// One track per clip, all on the video's time scale: the ruler travels the whole video, a bar body
// scrubs inside its clip, the ⠿ grip moves the clip, the edges resize it.
export default function TimelineTracks({ candidates, showCandidates, selectedKey, setSelectedKey, KeyPopover }) {
  const project = useStore((s) => s.project);
  const clipId = useStore((s) => s.clipId);
  const edits = useStore((s) => s.edits);
  const focusClipId = useStore((s) => s.focusClipId);
  useStore((s) => s.frame);
  const store = useStore.getState();
  const [drag, setDrag] = useState(null);
  const [renaming, setRenaming] = useState(null);

  const full = clipId === FULL;
  const total = Math.max(project.frames - 1, 1);
  const keys = full ? [] : edits.keys?.[clipId] || [];
  const playheadSource = store.sourceFrame();
  const sortedClips = [...project.clips].sort((a, b) => a.start - b.start);
  const percent = (value) => `${(value / total) * 100}%`;
  const seconds = Array.from({ length: Math.floor(total / project.fps) + 1 }, (_, i) => i);
  const tickEvery = seconds.length > 40 ? 5 : seconds.length > 15 ? 2 : 1;

  const fromElement = (element, event) => {
    const rect = element.getBoundingClientRect();
    return Math.round(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * total);
  };

  const followPointer = (onMove, onUp) => {
    const move = (e) => onMove(e);
    const up = (e) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      onUp?.(e);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const seekFrom = (event, focus) => {
    if (event.button !== 0) return;
    const lane = event.currentTarget;
    store.setPlaying(false);
    if (focus) useStore.setState({ focusClipId: focus });
    store.seekSource(fromElement(lane, event));
    followPointer((e) => useStore.getState().setFrame(fromElement(lane, e)));
  };

  const scrubClip = (event, c) => {
    if (event.button !== 0 || event.detail > 1) return;
    event.stopPropagation();
    const lane = event.currentTarget.parentElement;
    store.setPlaying(false);
    const toClip = (e) => (Math.min(Math.max(fromElement(lane, e), c.start), c.end) - c.start) / (c.speed || 1);
    if (c.id !== clipId) store.selectClip(c.id, toClip(event));
    else store.setFrame(toClip(event));
    followPointer((e) => {
      if (useStore.getState().clipId === c.id) useStore.getState().setFrame(toClip(e));
    });
  };

  const moveClip = (event, c) => {
    if (event.button !== 0 || event.detail > 1) return;
    event.stopPropagation();
    const lane = event.currentTarget.closest('.track-lane');
    store.setPlaying(false);
    const origin = fromElement(lane, event);
    const length = c.end - c.start;
    const shifted = (e) => Math.max(0, Math.min(total - length, c.start + fromElement(lane, e) - origin));
    followPointer(
      (e) => setDrag({ id: c.id, start: shifted(e), end: shifted(e) + length }),
      (e) => {
        setDrag(null);
        const start = shifted(e);
        if (start !== c.start) store.updateClip(c.id, { start, end: start + length });
      },
    );
  };

  const resizeClip = (event, c, edge) => {
    event.stopPropagation();
    const lane = event.currentTarget.closest('.track-lane');
    store.setPlaying(false);
    const bounds = (e) => {
      const value = fromElement(lane, e);
      return edge === 'start' ? { start: Math.min(value, c.end - 2), end: c.end } : { start: c.start, end: Math.max(value, c.start + 2) };
    };
    followPointer(
      (e) => setDrag({ id: c.id, ...bounds(e) }),
      (e) => {
        setDrag(null);
        store.updateClip(c.id, bounds(e));
      },
    );
  };

  const commitRename = (c, name) => {
    setRenaming(null);
    if (name && name !== c.name) store.updateClip(c.id, { name });
  };

  const selectKey = (event, index, key) => {
    event.stopPropagation();
    if (event.button !== 0) return;
    store.setPlaying(false);
    setSelectedKey(index);
    store.setFrame(key.frame);
    store.selectBone(key.bone);
  };

  return (
    <div className="tracks">
      <div className="track ruler-track">
        <button className={`track-label ${full ? 'active' : ''}`} onClick={() => store.selectClip(FULL, Math.round(playheadSource))} title="Parcourir toute la vidéo">
          <span className="track-name">Vidéo entière</span>
        </button>
        <div className="track-lane ruler" onPointerDown={(e) => seekFrom(e)}>
          {seconds
            .filter((s) => s % tickEvery === 0)
            .map((s) => (
              <span key={s} className="tick" style={{ left: percent(s * project.fps) }}>
                {s}s
              </span>
            ))}
          {showCandidates &&
            candidates.map((c) => (
              <span key={c.frame} className={`cut-mark ${c.on ? 'on' : ''}`} style={{ left: percent(c.frame) }} title={`coupe proposée · score ${c.score}`} />
            ))}
          <div className="playhead" style={{ left: percent(playheadSource) }} />
        </div>
      </div>

      <div className="track-list">
        {sortedClips.map((c) => {
          const color = CLIP_COLORS[project.clips.indexOf(c) % CLIP_COLORS.length];
          const start = drag?.id === c.id ? drag.start : c.start;
          const end = drag?.id === c.id ? drag.end : c.end;
          const active = c.id === clipId;
          const span = Math.max(end - start, 1);
          const keyLeft = (key) => ((key.frame * (c.speed || 1)) / span) * 100;
          return (
            <div key={c.id} className={`track ${active ? 'active' : ''} ${full && c.id === focusClipId ? 'focused' : ''}`} style={{ '--clip-color': color }}>
              <button className="track-label" onClick={() => store.selectClip(c.id)} onDoubleClick={() => setRenaming(c.id)} title="Clic : éditer ce clip · double-clic : renommer">
                <span className="swatch" />
                {renaming === c.id ? (
                  <input
                    className="track-rename mono"
                    autoFocus
                    defaultValue={c.name}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => commitRename(c, e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur();
                      if (e.key === 'Escape') setRenaming(null);
                    }}
                  />
                ) : (
                  <span className="track-name mono">{c.name}</span>
                )}
                <span className="muted small">{(span / project.fps).toFixed(1)}s</span>
              </button>
              <div className="track-lane" onPointerDown={(e) => seekFrom(e, c.id)}>
                <div className="track-bar" style={{ left: percent(start), width: percent(span) }} onPointerDown={(e) => scrubClip(e, c)}>
                  <span className="bar-grip" onPointerDown={(e) => moveClip(e, c)} title="Glisser pour déplacer le clip">
                    ⠿
                  </span>
                  <span className="handle start" onPointerDown={(e) => resizeClip(e, c, 'start')} title="Début du clip" />
                  <span className="handle end" onPointerDown={(e) => resizeClip(e, c, 'end')} title="Fin du clip" />
                  {active &&
                    keys.map((key, index) => (
                      <span
                        key={index}
                        className={`key ${selectedKey === index ? 'selected' : ''}`}
                        style={{ left: `${keyLeft(key)}%` }}
                        title={`${key.bone} · image ${key.frame}`}
                        onPointerDown={(e) => selectKey(e, index, key)}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          setSelectedKey(null);
                          store.removeKey(index);
                        }}
                      />
                    ))}
                  {active && selectedKey !== null && keys[selectedKey] && (
                    <KeyPopover
                      keyData={keys[selectedKey]}
                      left={keyLeft(keys[selectedKey])}
                      onDelete={() => {
                        store.removeKey(selectedKey);
                        setSelectedKey(null);
                      }}
                      onClose={() => setSelectedKey(null)}
                    />
                  )}
                </div>
                <div className="playhead" style={{ left: percent(playheadSource) }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
