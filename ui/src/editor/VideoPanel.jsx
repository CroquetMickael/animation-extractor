import { useEffect, useRef, useState } from 'react';
import { api, decodeFloats } from '../api.js';
import { useStore } from '../store.js';

const LAYOUT_KEY = 'animx.videoFloat';
const MIN_WIDTH = 220;
const DEFAULT_LAYOUT = { x: 16, y: 60, width: 360 };

export function sourceFrame(clip, frame) {
  return clip.start + frame * (clip.speed || 1);
}

function readLayout() {
  try {
    return { ...DEFAULT_LAYOUT, ...JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}') };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

function saveLayout(layout) {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    // storage unavailable: the window simply won't remember its place
  }
}

// Source video as a floating window over the 3D stage: draggable by its header, resizable from the corner.
export default function VideoPanel() {
  const video = useRef(null);
  const canvas = useRef(null);
  const frameRef = useRef(null);
  const [overlay, setOverlay] = useState(null);
  const [layout, setLayout] = useState(readLayout);
  const projectId = useStore((s) => s.projectId);
  const project = useStore((s) => s.project);
  const clipId = useStore((s) => s.clipId);
  const frame = useStore((s) => s.frame);
  const showOverlay = useStore((s) => s.showOverlay);
  const showVideo = useStore((s) => s.showVideo);
  const { toggleOverlay, setShowVideo } = useStore.getState();
  const captures = project?.captures;
  const engine = project?.settings.engine;

  useEffect(() => {
    api.overlay(projectId).then((data) => {
      if (!data.available) {
        setOverlay(null);
        return;
      }
      setOverlay({ ...data, left: new Set(data.left), data: decodeFloats(data.data) });
    });
  }, [projectId, captures?.mediapipe, captures?.gvhmr, engine]);

  const clip = project?.clips.find((c) => c.id === clipId);
  const current = clip ? Math.round(sourceFrame(clip, frame)) : Math.round(frame);

  useEffect(() => {
    if (!video.current || !project) return;
    const target = (current + 0.5) / project.fps;
    if (Math.abs(video.current.currentTime - target) > 0.5 / project.fps) video.current.currentTime = target;
  }, [current, project, showVideo]);

  useEffect(() => {
    const ctx = canvas.current?.getContext('2d');
    if (!ctx) return;
    const { width, height } = canvas.current;
    ctx.clearRect(0, 0, width, height);
    if (!overlay || !showOverlay || current >= overlay.frames) return;
    const base = current * overlay.points * 3;
    const at = (i) => [overlay.data[base + i * 3] * width, overlay.data[base + i * 3 + 1] * height];
    ctx.lineWidth = Math.max(2, width / 260);
    for (const [a, b] of overlay.links) {
      const pa = at(a);
      const pb = at(b);
      if (Number.isNaN(pa[0]) || Number.isNaN(pb[0])) continue;
      ctx.strokeStyle = overlay.left.has(a) || overlay.left.has(b) ? 'rgba(79,209,255,0.95)' : 'rgba(255,172,0,0.95)';
      ctx.beginPath();
      ctx.moveTo(pa[0], pa[1]);
      ctx.lineTo(pb[0], pb[1]);
      ctx.stroke();
    }
  }, [overlay, current, showOverlay, showVideo]);

  if (!project || !showVideo) return null;
  const [w, h] = project.size;

  const startPointer = (event, onMove) => {
    event.preventDefault();
    event.stopPropagation();
    const origin = { x: event.clientX, y: event.clientY, layout };
    const stage = frameRef.current.parentElement.getBoundingClientRect();
    let latest = layout;
    const move = (e) => {
      latest = onMove(e.clientX - origin.x, e.clientY - origin.y, origin.layout, stage);
      setLayout(latest);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      saveLayout(latest);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const drag = (event) =>
    startPointer(event, (dx, dy, from, stage) => ({
      ...from,
      x: Math.max(0, Math.min(stage.width - 80, from.x + dx)),
      y: Math.max(0, Math.min(stage.height - 40, from.y + dy)),
    }));

  const resize = (event) =>
    startPointer(event, (dx, _dy, from, stage) => ({
      ...from,
      width: Math.max(MIN_WIDTH, Math.min(stage.width - from.x, from.width + dx)),
    }));

  return (
    <div ref={frameRef} className="video-float" style={{ left: layout.x, top: layout.y, width: layout.width }}>
      <div className="video-float-header" onPointerDown={drag}>
        <span className="video-float-title">Vidéo</span>
        <span className="muted mono small">
          img {current} · {(current / project.fps).toFixed(2)} s
        </span>
        <div className="video-float-actions" onPointerDown={(e) => e.stopPropagation()}>
          <button
            className={`icon-toggle ${showOverlay ? 'on' : ''}`}
            onClick={toggleOverlay}
            title={`Squelette compris par ${overlay?.source === 'gvhmr' ? 'GVHMR' : 'MediaPipe'} (bleu = gauche)`}
          >
            ⌇
          </button>
          <button className="icon-toggle" onClick={() => setShowVideo(false)} title="Masquer la vidéo">
            ✕
          </button>
        </div>
      </div>
      <div className="video-frame" style={{ aspectRatio: `${w} / ${h}` }}>
        <video ref={video} src={api.videoUrl(projectId)} muted playsInline preload="auto" />
        <canvas ref={canvas} width={w} height={h} />
      </div>
      <span className="video-float-resize" onPointerDown={resize} title="Redimensionner" />
    </div>
  );
}
