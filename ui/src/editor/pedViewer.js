import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';

const EDITABLE = /^SKEL_(ROOT|Pelvis|Spine\d|Neck_1|Head|[LR]_(Thigh|Calf|Foot|Toe0|Clavicle|UpperArm|Forearm|Hand|Finger\d\d))$/;
const MARKER_COLOR = 0xffac00;
const MARKER_SELECTED = 0x4fd1ff;

// GTA peds are Z-up; three.js is Y-up. Everything GTA lives under `gtaSpace`.
export class PedViewer {
  constructor(container) {
    this.container = container;
    this.bones = new Map();
    this.markers = [];
    this.motion = null;
    this.selected = null;
    this.onSelect = null;
    this.onCommit = null;
    this.dragStart = null;
    this.transformMode = 'rotate';
    this.onTranslate = null;
    this.followVideoCamera = false;
    this.followPed = true;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x15151d);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.05, 100);
    this.camera.position.set(1.6, 1.4, 3.2);

    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.target.set(0, 0.95, 0);
    this.orbit.update();

    this.gizmo = new TransformControls(this.camera, this.renderer.domElement);
    this.gizmo.setMode('rotate');
    this.gizmo.setSpace('local');
    this.gizmo.setSize(0.7);
    this.gizmo.addEventListener('dragging-changed', (event) => this.onDragging(event.value));
    this.scene.add(this.gizmo.getHelper());

    this.addEnvironment();

    this.gtaSpace = new THREE.Group();
    this.gtaSpace.rotation.x = -Math.PI / 2;
    this.gtaSpace.position.y = 1.0;
    this.scene.add(this.gtaSpace);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.renderer.domElement.addEventListener('pointerdown', (e) => this.onPointerDown(e));

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.renderer.setAnimationLoop(() => this.renderer.render(this.scene, this.camera));
  }

  addEnvironment() {
    this.scene.add(new THREE.HemisphereLight(0xdde4ff, 0x2a2420, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(2, 5, 3);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -3;
    sun.shadow.camera.right = 3;
    sun.shadow.camera.top = 3;
    sun.shadow.camera.bottom = -3;
    this.scene.add(sun);

    const floor = new THREE.Mesh(new THREE.CircleGeometry(6, 64), new THREE.MeshStandardMaterial({ color: 0x23232f, roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.scene.add(floor);
    const grid = new THREE.GridHelper(12, 24, 0x3a3a4c, 0x2b2b38);
    grid.position.y = 0.001;
    this.scene.add(grid);

    const forward = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.01, 0), 0.6, 0xffac00, 0.12, 0.06);
    this.scene.add(forward);
  }

  async loadPed(ped) {
    if (this.ped) {
      this.gtaSpace.remove(this.ped);
      this.gizmo.detach();
      this.markers = [];
      this.bones.clear();
    }
    const gltf = await new GLTFLoader().loadAsync(`/api/peds/${ped}.glb`);
    this.ped = gltf.scene;
    this.ped.traverse((node) => {
      if (node.isMesh) {
        node.castShadow = true;
        node.frustumCulled = false;
      }
      if (node.isBone || node.name.startsWith('SKEL_') || /^(IK|PH|MH|RB|SM|EO|FB|FACIAL|SPR)_/.test(node.name)) {
        this.bones.set(node.name, node);
      }
    });
    this.gtaSpace.add(this.ped);
    this.addMarkers();
    // The motion may have arrived before the model: rebind its bone list to the bones that now exist.
    if (this.motion) {
      const frame = this.frame || 0;
      this.setMotion(this.motion);
      this.applyFrame(frame);
    }
  }

  addMarkers() {
    const geometry = new THREE.SphereGeometry(1, 12, 8);
    for (const [name, bone] of this.bones) {
      if (!EDITABLE.test(name)) continue;
      const finger = name.includes('Finger');
      const material = new THREE.MeshBasicMaterial({ color: MARKER_COLOR, depthTest: false, transparent: true, opacity: 0.85 });
      const marker = new THREE.Mesh(geometry, material);
      marker.scale.setScalar(finger ? 0.008 : 0.018);
      marker.renderOrder = 10;
      marker.userData.bone = name;
      bone.add(marker);
      this.markers.push(marker);
    }
  }

  setMarkersVisible(visible) {
    for (const marker of this.markers) marker.visible = visible;
  }

  setMotion(motion) {
    this.motion = motion;
    this.boneIndex = motion ? motion.bones.map((name) => this.bones.get(name) || null) : [];
    if (motion) this.applyFrame(0);
  }

  applyFrame(frame) {
    this.frame = frame;
    const motion = this.motion;
    if (!motion || this.dragStart) return;
    const count = motion.bones.length;
    const base = frame * count * 4;
    for (let b = 0; b < count; b++) {
      const bone = this.boneIndex[b];
      if (!bone) continue;
      const o = base + b * 4;
      bone.quaternion.set(motion.rotations[o], motion.rotations[o + 1], motion.rotations[o + 2], motion.rotations[o + 3]);
    }
    const root = this.bones.get('SKEL_ROOT');
    if (root) {
      const r = frame * 3;
      root.position.set(motion.root[r], motion.root[r + 1], motion.root[r + 2]);
    }
    this.applyMover(frame);
    if (this.followVideoCamera) this.placeVideoCamera(frame);
    else if (this.followPed) this.trackPed();
  }

  // The mover is the entity's own path: move the whole ped with it, as the game does.
  applyMover(frame) {
    if (!this.ped) return;
    const mover = this.motion?.mover;
    if (!mover) {
      this.ped.position.set(0, 0, 0);
      this.ped.quaternion.identity();
      return;
    }
    const t = frame * 3;
    const q = frame * 4;
    this.ped.position.set(mover.translation[t] - mover.translation[0], mover.translation[t + 1] - mover.translation[1], 0);
    this.ped.quaternion.set(mover.rotation[q], mover.rotation[q + 1], mover.rotation[q + 2], mover.rotation[q + 3]);
  }

  // Keeps the orbit pivot on the pelvis so a travelling clip stays framed; angle and zoom are kept.
  trackPed() {
    const pelvis = this.bones.get('SKEL_Pelvis');
    if (!pelvis || !this.ped) return;
    this.ped.updateMatrixWorld(true);
    const target = pelvis.getWorldPosition(new THREE.Vector3());
    target.y = 0.95;
    const delta = target.sub(this.orbit.target);
    this.orbit.target.add(delta);
    this.camera.position.add(delta);
    this.orbit.update();
  }

  setFollowPed(follow) {
    this.followPed = follow;
    if (follow && !this.followVideoCamera) this.trackPed();
  }

  setFollowVideoCamera(follow) {
    this.followVideoCamera = follow && !!this.motion?.camera;
    this.orbit.enabled = !this.followVideoCamera;
    if (this.followVideoCamera) {
      this.placeVideoCamera(this.frame || 0);
      return;
    }
    this.camera.fov = 40;
    this.camera.up.set(0, 1, 0);
    this.camera.updateProjectionMatrix();
    this.focus();
  }

  // Camera vectors are in GTA space (Z up); gtaSpace's rotation brings them into the scene.
  placeVideoCamera(frame) {
    const cam = this.motion?.camera;
    const pelvis = this.bones.get('SKEL_Pelvis');
    if (!cam || !pelvis) return;
    const i = frame * 3;
    const toScene = (array) => new THREE.Vector3(array[i], array[i + 1], array[i + 2]).applyQuaternion(this.gtaSpace.quaternion);
    this.ped.updateMatrixWorld(true);
    const target = pelvis.getWorldPosition(new THREE.Vector3());
    this.camera.position.copy(target).add(toScene(cam.offset));
    this.camera.up.copy(toScene(cam.up).normalize());
    this.camera.lookAt(this.camera.position.clone().add(toScene(cam.forward)));
    if (this.camera.fov !== cam.fov) {
      this.camera.fov = cam.fov;
      this.camera.updateProjectionMatrix();
    }
  }

  select(name) {
    this.selected = name;
    for (const marker of this.markers) {
      marker.material.color.setHex(marker.userData.bone === name ? MARKER_SELECTED : MARKER_COLOR);
    }
    const bone = name ? this.bones.get(name) : null;
    if (bone) this.gizmo.attach(bone);
    else this.gizmo.detach();
  }

  // 'rotate' turns the selected joint; 'translate' drags it with world-aligned arrows (the pipeline
  // solves the limb by IK, see animx/edits.apply_move_keys).
  setTransformMode(mode) {
    this.transformMode = mode;
    this.gizmo.setMode(mode);
    this.gizmo.setSpace(mode === 'translate' ? 'world' : 'local');
    this.select(this.selected);
  }

  onPointerDown(event) {
    if (this.gizmo.dragging || event.button !== 0) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.markers.filter((m) => m.visible), false);
    if (hits.length > 0) this.onSelect?.(hits[0].object.userData.bone);
  }

  onDragging(dragging) {
    this.orbit.enabled = !dragging;
    const bone = this.gizmo.object;
    if (!bone) return;
    if (dragging) {
      this.dragStart = { quaternion: bone.quaternion.clone(), world: bone.getWorldPosition(new THREE.Vector3()) };
      return;
    }
    const start = this.dragStart;
    this.dragStart = null;
    if (!start) return;
    if (this.transformMode === 'translate') {
      // The move key is stored in entity space: the space SKEL_ROOT's position lives in (the root track).
      const entity = this.bones.get('SKEL_ROOT')?.parent || this.ped;
      const after = entity.worldToLocal(bone.getWorldPosition(new THREE.Vector3()));
      const delta = after.sub(entity.worldToLocal(start.world.clone()));
      if (delta.lengthSq() < 1e-8) return;
      this.onTranslate?.(bone.name, [delta.x, delta.y, delta.z]);
      return;
    }
    const before = start.quaternion;
    const offset = before.clone().invert().multiply(bone.quaternion);
    if (Math.abs(offset.w) > 0.99999) return;
    this.onCommit?.(bone.name, [offset.x, offset.y, offset.z, offset.w]);
  }

  // Preset viewpoints relative to where the ped faces at the current frame (GTA +Y is its forward).
  setView(view) {
    if (this.followVideoCamera || !this.ped) return;
    const pelvis = this.bones.get('SKEL_Pelvis');
    const root = this.bones.get('SKEL_ROOT');
    if (!pelvis || !root) return;
    this.ped.updateMatrixWorld(true);
    const target = pelvis.getWorldPosition(new THREE.Vector3());
    target.y = 0.95;
    const facing = new THREE.Vector3(0, 1, 0).applyQuaternion(root.getWorldQuaternion(new THREE.Quaternion()));
    facing.y = 0;
    if (facing.lengthSq() < 1e-6) facing.set(0, 0, -1);
    facing.normalize();
    const right = new THREE.Vector3().crossVectors(facing, new THREE.Vector3(0, 1, 0)).normalize();
    const directions = {
      front: facing.clone(),
      back: facing.clone().negate(),
      left: right.clone().negate(),
      right: right.clone(),
    };
    this.orbit.target.copy(target);
    if (view === 'top') {
      this.camera.position.copy(target).add(new THREE.Vector3(0, 4, 0)).addScaledVector(facing, -0.01);
    } else {
      this.camera.position.copy(target).addScaledVector(directions[view], 3.2).add(new THREE.Vector3(0, view === 'back' ? 0.5 : 0.3, 0));
    }
    this.orbit.update();
  }

  focus() {
    if (this.followVideoCamera) return;
    this.orbit.target.set(0, 0.95, 0);
    this.camera.position.set(1.6, 1.4, 3.2);
    this.orbit.update();
    if (this.followPed) this.trackPed();
  }

  resize() {
    const { clientWidth, clientHeight } = this.container;
    if (!clientWidth || !clientHeight) return;
    this.renderer.setSize(clientWidth, clientHeight);
    this.camera.aspect = clientWidth / clientHeight;
    this.camera.updateProjectionMatrix();
  }

  dispose() {
    this.resizeObserver.disconnect();
    this.renderer.setAnimationLoop(null);
    this.gizmo.dispose();
    this.orbit.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
