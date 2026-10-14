import { useState } from 'react';
import { FULL, useStore } from '../../store.js';
import { CommitInput, Slider, Toggle } from '../fields.jsx';
import { CLIP_COLORS } from '../Timeline.jsx';

export default function ClipTab() {
  const project = useStore((s) => s.project);
  const clipId = useStore((s) => s.clipId);
  useStore((s) => s.frame);
  const store = useStore.getState();
  const [message, setMessage] = useState(null);
  const clip = clipId === FULL ? store.targetClip() : project.clips.find((c) => c.id === clipId);
  const fps = project.fps;
  const sorted = [...project.clips].sort((a, b) => a.start - b.start);
  const colorOf = (c) => CLIP_COLORS[project.clips.indexOf(c) % CLIP_COLORS.length];

  const removeClip = async (target) => {
    if (project.clips.length <= 1 || !window.confirm(`Supprimer le clip ${target.name} ?`)) return;
    const clips = project.clips.filter((c) => c.id !== target.id);
    await store.patchProject({ clips });
    if (clipId === target.id) await store.selectClip(clips[0].id);
  };

  const duplicateClip = async () => {
    const copy = { ...clip, id: undefined, name: `${clip.name}_b` };
    await store.patchProject({ clips: [...project.clips, copy] });
  };

  const act = async (action) => {
    const error = await action();
    setMessage(error);
  };

  return (
    <div className="stack">
      <div className="clip-table">
        <button className={`clip-row full ${clipId === FULL ? 'active' : ''}`} onClick={() => store.selectClip(FULL, Math.round(store.sourceFrame()))}>
          <span>▤ Vidéo entière</span>
          <span className="muted">{(project.frames / fps).toFixed(1)} s — pour découper</span>
        </button>
        {sorted.map((c) => (
          <div key={c.id} className={`clip-row ${c.id === clipId ? 'active' : ''}`} style={{ '--clip-color': colorOf(c) }} onClick={() => c.id !== clipId && store.selectClip(c.id)}>
            <span className="swatch" />
            <CommitInput className="text mono inline-name" value={c.name} onCommit={(name) => store.updateClip(c.id, { name })} onClick={(e) => e.stopPropagation()} title="Nom du clip dans le dictionnaire (TaskPlayAnim)" />
            <span className="muted small nowrap">
              {((c.end - c.start) / fps).toFixed(1)} s{c.loop ? ' ⟲' : ''}
            </span>
            <button className="icon" onClick={(e) => { e.stopPropagation(); removeClip(c); }} disabled={project.clips.length <= 1} title="Supprimer">
              ✕
            </button>
          </div>
        ))}
      </div>
      <p className="muted small">
        Découpe : <kbd>C</kbd> couper · <kbd>I</kbd>/<kbd>O</kbd> début/fin · <kbd>N</kbd> nouveau clip · <kbd>D</kbd> détection auto. Double-clic sur un clip de la timeline pour le renommer.
      </p>
      {message && <p className="error small">{message}</p>}

      {clip && (
        <>
          <div className="row">
            <button className="secondary" onClick={duplicateClip}>Dupliquer</button>
            <button className="secondary" onClick={() => act(() => store.mergeNext(clip.id))}>Fusionner avec le suivant</button>
          </div>
          <div className="row">
            <label className="field">
              Début (image)
              <CommitInput type="number" value={clip.start} min={0} max={clip.end - 1} onCommit={(start) => store.updateClip(clip.id, { start })} />
            </label>
            <label className="field">
              Fin (image)
              <CommitInput type="number" value={clip.end} min={clip.start + 1} max={project.frames - 1} onCommit={(end) => store.updateClip(clip.id, { end })} />
            </label>
          </div>

          <Toggle label="Boucle" checked={clip.loop} onChange={(loop) => store.updateClip(clip.id, { loop })} hint="Fondu fin → début pour une lecture en boucle sans saut" />
          {clip.loop && (
            <Slider label="Fondu de boucle" value={clip.loop_blend} min={2} max={30} step={1} format={(v) => `${v} img`} onCommit={(loop_blend) => store.updateClip(clip.id, { loop_blend })} />
          )}
          <label className="field">
            Déplacement
            <select value={clip.motion || 'inplace'} onChange={(e) => store.updateClip(clip.id, { motion: e.target.value })}>
              <option value="inplace">Sur place (emotes, idles, boucles)</option>
              <option value="root">Dans le corps (revient à sa place à la fin)</option>
              <option value="mover">Mover : le ped se déplace en jeu</option>
              <option value="mover_turn">Mover + rotation : se déplace et pivote</option>
            </select>
          </label>
          {(clip.motion === 'mover' || clip.motion === 'mover_turn') && <TravelSpeed clip={clip} />}
          {(clip.motion || 'inplace') !== 'inplace' && (
            <Toggle
              label="Déplacement déduit des pieds"
              checked={clip.foot_driven !== false}
              onChange={(foot_driven) => store.updateClip(clip.id, { foot_driven })}
              hint="Le pied posé au sol reste immobile, donc le corps avance d'autant. Indispensable pour les animations de jeu jouées sur place (le pied glisse comme sur un tapis roulant) ; sans effet notable sur une vraie vidéo où la personne se déplace déjà."
            />
          )}
          <Toggle label="Lire à l'envers" checked={clip.reverse} onChange={(reverse) => store.updateClip(clip.id, { reverse })} hint="L'animation est jouée à rebours : une marche avant devient une marche arrière (le mover recule aussi)" />
          <Toggle label="Miroir gauche ↔ droite" checked={clip.mirror} onChange={(mirror) => store.updateClip(clip.id, { mirror })} hint="Échange le côté gauche et le côté droit : une esquive à droite devient une esquive à gauche" />
          <Toggle label="Pieds verrouillés" checked={clip.foot_lock} onChange={(foot_lock) => store.updateClip(clip.id, { foot_lock })} hint="Empêche les pieds de glisser quand ils sont au sol" />
          <Toggle label="Bloquer l'orientation" checked={clip.lock_heading} onChange={(lock_heading) => store.updateClip(clip.id, { lock_heading })} hint="Annule les rotations du corps autour de l'axe vertical" />
          {project.settings.engine === 'gvhmr' && (
            <label className="field">
              Hauteur du corps (ce clip)
              <select value={clip.ground || ''} onChange={(e) => store.updateClip(clip.id, { ground: e.target.value || null })}>
                <option value="">Réglage du projet ({GROUND_LABELS[project.settings.ground]})</option>
                <option value="planted">{GROUND_LABELS.planted}</option>
                <option value="auto">{GROUND_LABELS.auto}</option>
                <option value="tracked">{GROUND_LABELS.tracked}</option>
              </select>
            </label>
          )}
          <div className="row">
            <HandSelect label="Main gauche" value={clip.hand_left} onChange={(hand_left) => store.updateClip(clip.id, { hand_left })} />
            <HandSelect label="Main droite" value={clip.hand_right} onChange={(hand_right) => store.updateClip(clip.id, { hand_right })} />
          </div>
          <Slider label="Vitesse" value={clip.speed} min={0.25} max={2} step={0.05} format={(v) => `×${v.toFixed(2)}`} onCommit={(speed) => store.updateClip(clip.id, { speed })} />
        </>
      )}
    </div>
  );
}

const HAND_POSES = [
  ['relaxed', 'Détendue'],
  ['loose', 'Poing léger'],
  ['fist', 'Poing fermé'],
  ['open', 'Ouverte (raide)'],
];

function HandSelect({ label, value, onChange }) {
  return (
    <label className="field">
      {label}
      <select value={value || 'relaxed'} onChange={(e) => onChange(e.target.value)}>
        {HAND_POSES.map(([id, text]) => (
          <option key={id} value={id}>{text}</option>
        ))}
      </select>
    </label>
  );
}

const GROUND_LABELS = {
  planted: 'Pieds toujours au sol',
  auto: 'Auto : sauts conservés',
  tracked: 'Suivie brute',
};

const SPEED_PRESETS = [
  ['auto', 'Auto (allure détectée)'],
  ['feet', 'Mesurée par les pieds'],
  ['1.71', 'Marche GTA · 1,7 m/s'],
  ['3.3', 'Jogging · 3,3 m/s'],
  ['5.11', 'Course GTA · 5,1 m/s'],
  ['6.85', 'Sprint GTA · 6,85 m/s'],
  ['custom', 'Personnalisée…'],
];

function TravelSpeed({ clip }) {
  const travel = useStore((s) => (s.clipId === clip.id ? s.motion?.travel : null));
  const updateClip = useStore((s) => s.updateClip);
  const value = clip.travel ?? 'auto';
  const preset = typeof value === 'number' ? (SPEED_PRESETS.some(([id]) => Number(id) === value) ? String(value) : 'custom') : value;
  const choose = (id) => {
    if (id === 'custom') updateClip(clip.id, { travel: travel?.applied_speed || 3 });
    else updateClip(clip.id, { travel: id === 'auto' || id === 'feet' ? id : Number(id) });
  };
  const analysis = travel?.analysis;
  return (
    <div className="travel-box">
      <label className="field">
        Vitesse du déplacement
        <select value={preset} onChange={(e) => choose(e.target.value)}>
          {SPEED_PRESETS.map(([id, text]) => (
            <option key={id} value={id}>{text}</option>
          ))}
        </select>
      </label>
      {preset === 'custom' && (
        <Slider label="Vitesse" value={value} min={0.5} max={9} step={0.1} format={(v) => `${v.toFixed(1)} m/s`} onCommit={(v) => updateClip(clip.id, { travel: v })} />
      )}
      <LateralOffset clip={clip} measured={travel?.measured_lateral} />
      {travel && (
        <p className="muted small">
          {analysis ? `Allure : ${analysis.gait} (${analysis.cadence.toFixed(2)} pas/s)` : 'Allure : pas de rythme régulier détecté'}
          {' · '}mesuré {travel.measured_speed.toFixed(1)} m/s → appliqué <strong>{travel.applied_speed.toFixed(1)} m/s</strong>
        </p>
      )}
    </div>
  );
}

const LATERAL_PRESETS = [
  ['measured', 'Mesuré dans la vidéo'],
  ['none', 'Aucun (tout droit)'],
  ['x1.5', 'Accentué ×1,5'],
  ['x2', 'Accentué ×2'],
  ['distance', 'Distance personnalisée…'],
];

function LateralOffset({ clip, measured }) {
  const updateClip = useStore((s) => s.updateClip);
  const value = clip.lateral ?? 'measured';
  const preset = typeof value === 'string' ? value : 'distance' in value ? 'distance' : `x${value.scale}`;
  const choose = (id) => {
    if (id === 'measured' || id === 'none') updateClip(clip.id, { lateral: id });
    else if (id === 'distance') updateClip(clip.id, { lateral: { distance: measured ? Math.round(measured * 10) / 10 : 1 } });
    else updateClip(clip.id, { lateral: { scale: Number(id.slice(1)) } });
  };
  const side = (v) => (Math.abs(v) < 0.05 ? 'au centre' : `${Math.abs(v).toFixed(1)} m à ${v > 0 ? 'droite' : 'gauche'}`);
  return (
    <>
      <label className="field">
        Écart latéral
        <select value={preset} onChange={(e) => choose(e.target.value)}>
          {LATERAL_PRESETS.map(([id, text]) => (
            <option key={id} value={id}>{text}</option>
          ))}
        </select>
      </label>
      {preset === 'distance' && (
        <Slider label="Décalage à la fin du clip" value={value.distance} min={-4} max={4} step={0.1} format={side} onCommit={(distance) => updateClip(clip.id, { lateral: { distance } })} />
      )}
      {measured !== undefined && measured !== null && <p className="muted small">Écart mesuré dans la vidéo : {side(measured)}</p>}
      {clip.mirror && preset !== 'none' && (
        <p className="muted small">
          Miroir actif : côté inversé dans l'animation finale
          {preset === 'distance' ? ` (${side(-value.distance)})` : ''}.
        </p>
      )}
    </>
  );
}
