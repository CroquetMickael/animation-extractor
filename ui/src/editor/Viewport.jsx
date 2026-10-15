import { useEffect, useRef, useState } from 'react';
import { FULL, useStore } from '../store.js';
import { PedViewer } from './pedViewer.js';

export default function Viewport() {
  const container = useRef(null);
  const viewer = useRef(null);
  const [showMarkers, setShowMarkers] = useState(true);
  const [videoCamera, setVideoCamera] = useState(false);
  const [followPed, setFollowPed] = useState(true);
  const ped = useStore((s) => s.project?.settings.ped);
  const motion = useStore((s) => s.motion);
  const frame = useStore((s) => s.frame);
  const selectedBone = useStore((s) => s.selectedBone);
  const motionLoading = useStore((s) => s.motionLoading);
  const motionError = useStore((s) => s.motionError);
  const editMode = useStore((s) => s.editMode);
  const setEditMode = useStore((s) => s.setEditMode);
  const transformMode = useStore((s) => s.transformMode);
  const setTransformMode = useStore((s) => s.setTransformMode);
  const showVideo = useStore((s) => s.showVideo);
  const setShowVideo = useStore((s) => s.setShowVideo);

  useEffect(() => {
    const instance = new PedViewer(container.current);
    instance.onSelect = (bone) => {
      // Whole-video and style previews have no clip to hold corrections.
      if (useStore.getState().clipId === FULL || useStore.getState().preview) return;
      useStore.getState().selectBone(bone);
    };
    instance.onCommit = (bone, offset) => {
      useStore.getState().setPlaying(false);
      useStore.getState().addBoneOffset(bone, offset);
    };
    instance.onTranslate = (bone, offset) => {
      useStore.getState().setPlaying(false);
      useStore.getState().addMoveKey(bone, offset);
    };
    viewer.current = instance;
    return () => instance.dispose();
  }, []);

  useEffect(() => {
    if (ped) viewer.current?.loadPed(ped);
  }, [ped]);

  useEffect(() => {
    viewer.current?.setMotion(motion);
    viewer.current?.applyFrame(useStore.getState().frame);
    viewer.current?.setFollowVideoCamera(videoCamera);
  }, [motion]);

  useEffect(() => {
    viewer.current?.setFollowVideoCamera(videoCamera);
  }, [videoCamera]);

  useEffect(() => {
    viewer.current?.setFollowPed(followPed);
  }, [followPed]);

  useEffect(() => {
    viewer.current?.applyFrame(frame);
  }, [frame]);

  useEffect(() => {
    viewer.current?.select(selectedBone);
  }, [selectedBone]);

  useEffect(() => {
    viewer.current?.setMarkersVisible(showMarkers);
  }, [showMarkers]);

  useEffect(() => {
    viewer.current?.setTransformMode(transformMode);
  }, [transformMode]);

  return (
    <div className="viewport">
      <div ref={container} className="viewport-canvas" />

      <div className="stage-toolbar">
        <div className="tool-cluster">
          <ToolButton on={showVideo} onClick={() => setShowVideo(!showVideo)} title="Afficher la vidéo source">
            Vidéo
          </ToolButton>
          <ToolButton on={showMarkers} onClick={() => setShowMarkers(!showMarkers)} title="Points d'articulation cliquables">
            Articulations
          </ToolButton>
        </div>
        <div className="tool-cluster">
          <ToolButton on={videoCamera} onClick={() => setVideoCamera(!videoCamera)} disabled={!motion?.camera} title="Voir le ped depuis la caméra de la vidéo">
            Caméra vidéo
          </ToolButton>
          <ToolButton on={followPed} onClick={() => setFollowPed(!followPed)} disabled={videoCamera} title="La caméra suit le ped quand il se déplace">
            Suivre
          </ToolButton>
          <ToolButton onClick={() => viewer.current?.focus()} disabled={videoCamera} title="Revenir au cadrage par défaut">
            Recentrer
          </ToolButton>
        </div>
        <div className="tool-cluster">
          {[['front', 'Face'], ['back', 'Dos'], ['left', 'Profil G'], ['right', 'Profil D'], ['top', 'Dessus']].map(([id, label]) => (
            <ToolButton key={id} onClick={() => viewer.current?.setView(id)} disabled={videoCamera} title={`Vue ${label.toLowerCase()} par rapport au ped (Dos = comme la caméra du jeu)`}>
              {label}
            </ToolButton>
          ))}
        </div>
      </div>

      {(motionLoading || motionError) && (
        <div className="stage-status">
          {motionLoading && <span className="mode-pill">Calcul…</span>}
          {motionError && <span className="mode-pill error">{motionError}</span>}
        </div>
      )}

      {selectedBone && (
        <div className="viewport-hint">
          <div className="hint-switch">
            <button className={transformMode === 'rotate' ? 'active' : ''} onClick={() => setTransformMode('rotate')} title="Tourner l'articulation sélectionnée">
              Tourner
            </button>
            <button className={transformMode === 'translate' ? 'active' : ''} onClick={() => setTransformMode('translate')} title="Déplacer l'articulation : le bras ou la jambe suit (IK), le bassin emmène tout le corps">
              Déplacer
            </button>
          </div>
          <strong>{selectedBone}</strong>
          {transformMode === 'rotate' ? (
            <>
              <span className="muted">tourne avec les anneaux, la retouche s'applique à :</span>
              <div className="hint-switch">
                <button className={editMode === 'key' ? 'active' : ''} onClick={() => setEditMode('key')} title="La correction s'estompe sur les images voisines (portée réglable dans l'onglet Os)">
                  ce clip
                </button>
                <button className={editMode === 'calibration' ? 'active' : ''} onClick={() => setEditMode('calibration')} title="Décalage permanent appliqué à toutes les images de tous les clips">
                  tous les clips
                </button>
              </div>
            </>
          ) : (
            <span className="muted">
              {selectedBone === 'SKEL_ROOT' || selectedBone === 'SKEL_Pelvis'
                ? 'tire les flèches : tout le corps suit'
                : 'tire les flèches : le membre suit en IK'}
              {' '}· sur ce clip, portée réglable dans l'onglet Os
            </span>
          )}
          <span className="muted">· Échap pour quitter</span>
        </div>
      )}
    </div>
  );
}

function ToolButton({ on, children, ...rest }) {
  return (
    <button className={`stage-tool ${on ? 'on' : ''}`} {...rest}>
      {children}
    </button>
  );
}
