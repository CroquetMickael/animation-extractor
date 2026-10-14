# animation-extractor

Outil vidéo → animation GTA V / FiveM (`.ycd`). Il capte le mouvement d'une personne dans une vidéo, le retarget sur le ped freemode, le nettoie et le compile en dictionnaire d'animations prêt à streamer. Un éditeur 3D sert à vérifier le résultat et à corriger les os du ped.

## Fonctionnalités

- **Capture** : MediaPipe (rapide) ou [GVHMR](https://github.com/zju3dv/GVHMR) (monde 3D, gravité estimée, plus fidèle).
- **Retargeting** sur `mp_m_freemode_01` / `mp_f_freemode_01`, extraits de ta propre installation de GTA V via [CodeWalker](https://github.com/dexyfex/CodeWalker).
- **Nettoyage** : lissage, recalage au sol, IK et verrouillage des pieds, placement des mains, poses de mains.
- **Découpe** : plusieurs clips dans une même vidéo (détection automatique des coupes), renommés pour le dictionnaire.
- **Déplacement** : sur place, root ou vraie piste *mover* (vitesse auto, cadence des pieds ou m/s, écart latéral), avec ou sans rotation.
- **Transformations** : miroir, lecture inversée, vitesse, boucle avec fondu.
- **Éditeur** : vidéo flottante, une piste par animation, retouches d'os par images clés, annuler/rétablir (Ctrl+Z / Ctrl+Y).
- **Démarches** : génère une ressource de *movement clipset* (idle, marche, course, sprint), avec `clip_sets.meta` à activer via `SetPedMovementClipset`.
- **Export** `.ycd` : pistes triées comme celles de Rockstar, tous les os SKEL écrits, pistes IK/PH, étiquettes de pas.

## Prérequis

- Windows 10/11 et un GPU NVIDIA (PyTorch CUDA 12.8, compatible RTX 50xx).
- Une installation de GTA V : les peds et les références sont lus localement, rien n'est redistribué.
- Le .NET 8 SDK, Node.js 20+, git et le lanceur Python `py`.

## Installation

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -GtaFolder "D:\GTAV"
```

Tout s'installe dans le dossier du projet : Python 3.10 isolé, dépendances, CodeWalker, `gtabridge`, peds extraits, modèles MediaPipe, GVHMR et ses poids, interface.

**GVHMR a besoin de `SMPLX_NEUTRAL.npz`.** Ce fichier est sous licence non commerciale, donc il n'est pas fourni. Crée un compte gratuit sur <https://smpl-x.is.tue.mpg.de>, télécharge le modèle, puis dépose-le dans `third_party/GVHMR/inputs/checkpoints/body_models/smplx/`. MediaPipe fonctionne sans ce fichier.

Une copie est aussi disponible sur Hugging Face : <https://huggingface.co/camenduru/SMPLer-X/blob/main/SMPLX_NEUTRAL.npz>. C'est un miroir non officiel, et la licence SMPL-X (usage non commercial) s'applique quelle que soit la source.

## Utilisation

```powershell
animx.bat            # ouvre l'éditeur sur http://127.0.0.1:8765
animx.bat doctor     # vérifie l'installation
```

1. Importe une vidéo, puis lance la capture.
2. Découpe et nomme les clips, règle le déplacement, le sol et les mains, et corrige les os si besoin.
3. Exporte le `.ycd` ou installe-le directement dans le dossier `stream/` d'une ressource.

`fivem/animx_test` est une ressource de test. La commande `/animx <dict> <clip> [vitesse] [flag] [blend] [noik]` joue un clip exporté sur ton ped, et `/animx stop` l'arrête.

## Structure

| Dossier | Contenu |
|---|---|
| `animx/` | Pipeline Python (capture, retargeting, nettoyage, mover, export YCD) et serveur FastAPI |
| `bridge/` | `gtabridge`, outil C# basé sur CodeWalker.Core (export du ped, YCD ↔ XML, dump de clips) |
| `ui/` | Éditeur React + three.js |
| `third_party/shims/` | Remplacements minimaux de `pytorch3d` et `wis3d` pour GVHMR |
| `fivem/animx_test/` | Ressource FiveM de test |

## Licences

Le code est sous GPL-3.0 (voir `LICENSE`). GTA V et ses assets appartiennent à Rockstar Games : l'outil les lit depuis ta copie du jeu et ne les redistribue pas. SMPL-X, GVHMR, MediaPipe et CodeWalker restent soumis à leurs propres licences.
