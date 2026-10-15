import { ROOT_OFFSET, useStore } from '../../store.js';
import { Slider } from '../fields.jsx';

const GROUPS = [
  ['Tronc', ['SKEL_ROOT', 'SKEL_Pelvis', 'SKEL_Spine0', 'SKEL_Spine1', 'SKEL_Spine2', 'SKEL_Spine3', 'SKEL_Neck_1', 'SKEL_Head']],
  ['Bras gauche', ['SKEL_L_Clavicle', 'SKEL_L_UpperArm', 'SKEL_L_Forearm', 'SKEL_L_Hand']],
  ['Bras droit', ['SKEL_R_Clavicle', 'SKEL_R_UpperArm', 'SKEL_R_Forearm', 'SKEL_R_Hand']],
  ['Jambe gauche', ['SKEL_L_Thigh', 'SKEL_L_Calf', 'SKEL_L_Foot', 'SKEL_L_Toe0']],
  ['Jambe droite', ['SKEL_R_Thigh', 'SKEL_R_Calf', 'SKEL_R_Foot', 'SKEL_R_Toe0']],
];

const keyLabel = (key) => {
  if (!key.t) return label(key.bone);
  const [x, y, z] = key.t.map((v) => Math.round(v * 100));
  return `${key.bone === ROOT_OFFSET ? 'Corps' : label(key.bone)} · déplacé ${x} / ${y} / ${z} cm`;
};

const label = (name) => name.replace('SKEL_', '').replace('_L_', ' G · ').replace('_R_', ' D · ').replace(/^L_/, 'G · ').replace(/^R_/, 'D · ');

export default function BonesTab() {
  const selectedBone = useStore((s) => s.selectedBone);
  const editMode = useStore((s) => s.editMode);
  const keyRadius = useStore((s) => s.keyRadius);
  const edits = useStore((s) => s.edits);
  const clipId = useStore((s) => s.clipId);
  const { selectBone, setEditMode, setKeyRadius, removeKey, clearCalibration, setFrame } = useStore.getState();
  const keys = edits.keys?.[clipId] || [];
  const calibration = Object.keys(edits.calibration || {});

  return (
    <div className="stack">
      <div className="segmented">
        <button className={editMode === 'key' ? 'active' : ''} onClick={() => setEditMode('key')}>
          Correction du clip
        </button>
        <button className={editMode === 'calibration' ? 'active' : ''} onClick={() => setEditMode('calibration')}>
          Calibration globale
        </button>
      </div>
      <p className="muted small">
        {editMode === 'key'
          ? "Tourne ou déplace (« Déplacer » dans la vue 3D) une articulation à l'image courante : la correction s'estompe sur les images voisines."
          : 'Décalage permanent d’un os, appliqué à toutes les images de tous les clips (erreur systématique).'}
      </p>
      {editMode === 'key' && (
        <Slider
          label="Portée de la correction"
          value={keyRadius}
          min={-1}
          max={90}
          step={1}
          format={(v) => (v < 0 ? 'tout le clip' : v === 0 ? 'cette image' : `±${v} img`)}
          onCommit={setKeyRadius}
        />
      )}

      <div className="bone-groups">
        {GROUPS.map(([title, bones]) => (
          <div key={title} className="bone-group">
            <span className="group-title">{title}</span>
            <div className="bone-chips">
              {bones.map((bone) => (
                <button key={bone} className={`chip ${bone === selectedBone ? 'active' : ''} ${edits.calibration?.[bone] ? 'calibrated' : ''}`} onClick={() => selectBone(bone)}>
                  {label(bone)}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="list-block">
        <span className="group-title">Corrections de ce clip ({keys.length})</span>
        {keys.length === 0 && <p className="muted small">Aucune.</p>}
        {keys.map((key, index) => (
          <div key={index} className="list-row">
            <button className="link" onClick={() => { setFrame(key.frame); selectBone(key.bone === ROOT_OFFSET ? 'SKEL_ROOT' : key.bone); }}>
              {keyLabel(key)} · img {key.frame} · {key.radius < 0 ? 'tout' : `±${key.radius}`}
            </button>
            <button className="icon" onClick={() => removeKey(index)} title="Supprimer">✕</button>
          </div>
        ))}
      </div>

      <div className="list-block">
        <span className="group-title">Calibration ({calibration.length})</span>
        {calibration.map((bone) => (
          <div key={bone} className="list-row">
            <span>{label(bone)}</span>
            <button className="icon" onClick={() => clearCalibration(bone)} title="Réinitialiser">✕</button>
          </div>
        ))}
        {calibration.length > 0 && (
          <button className="secondary" onClick={() => clearCalibration(null)}>Tout réinitialiser</button>
        )}
      </div>
    </div>
  );
}
