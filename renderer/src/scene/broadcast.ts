import * as T from 'three';
import { applyCamera } from '../camera/presets';
import { world, type Frame, type MatchInfo, type Player } from '../data/match';
import { createBall, projectedDiameter, ballScale } from './ball';
import { BALL_RADIUS_M, renderConfig, type RenderConfig } from './config';
import type { PlayerPose } from './motion';
import { RichStyle, richGait } from './rich';

/** Fixed world geometry: no random values or wall-clock-dependent animation. */
export class Broadcast {
  readonly renderer: T.WebGLRenderer;
  readonly scene = new T.Scene();
  readonly camera = new T.PerspectiveCamera(43, 16 / 9, 0.1, 400);
  private actors = new Map<number, T.Group>();
  private richStyle = new RichStyle();
  private rich = false;
  private pitchMeshes: T.Mesh[] = [];
  private cleanPitchMaterials: T.Material[] = [];
  private sky = new T.HemisphereLight(0xe9f6ff, 0x486332, 2);
  private fill = new T.DirectionalLight(0xc8deff, 0.8);
  private ball: T.Mesh;
  private config = renderConfig();
  private physicalBallMaterial = new T.MeshStandardMaterial({ color: '#ffffff', roughness: 0.8 });
  private cvBallMaterial = new T.MeshBasicMaterial({ color: '#fff052' });
  private sun = new T.DirectionalLight(0xffffff, 2.3);
  constructor(canvas: HTMLCanvasElement, private info: MatchInfo) {
    this.renderer = new T.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(1280, 720, false);
    this.renderer.outputColorSpace = T.SRGBColorSpace;
    this.renderer.shadowMap.type = T.PCFSoftShadowMap;
    this.scene.background = new T.Color('#243d45');
    this.scene.add(this.sky); this.fill.position.set(35, 25, -35); this.scene.add(this.fill);
    this.sun.position.set(-30, 65, 30); this.sun.castShadow = true;
    Object.assign(this.sun.shadow.camera, { left: -75, right: 75, top: 65, bottom: -65, far: 180 });
    this.sun.shadow.mapSize.set(2048, 2048); this.sun.shadow.bias = -0.0003;
    this.scene.add(this.sun);
    this.box(140, 0.2, 100, '#233b31', [0, -0.16, 0]);
    for (let i = 0; i < 14; i++) {
      const stripe = this.box(7.5, 0.05, 68, i % 2 ? '#398b49' : '#348044', [-48.75 + i * 7.5, -0.025, 0]);
      stripe.receiveShadow = true; this.pitchMeshes.push(stripe); this.cleanPitchMaterials.push(stripe.material as T.Material);
    }
    this.markings(); this.goals(); this.scene.add(this.richStyle.stadium);
    this.ball = createBall(); (this.ball.material as T.Material).dispose(); this.ball.material = this.physicalBallMaterial; this.scene.add(this.ball);
    applyCamera(this.camera, this.config.camera, this.ball.position);
    this.setRich(false);
  }
  private box(w: number, h: number, d: number, color: string, pos: number[], parent: T.Object3D = this.scene): T.Mesh {
    const mesh = new T.Mesh(new T.BoxGeometry(w, h, d), new T.MeshStandardMaterial({ color, roughness: 0.92 }));
    mesh.position.set(pos[0], pos[1], pos[2]); parent.add(mesh); return mesh;
  }
  private line(points: number[][], color = '#ffffff', parent: T.Object3D = this.scene): void {
    // Flat ribbons give markings real 12 cm width on all platforms (WebGL lines are often 1px).
    for (let i = 1; i < points.length; i++) {
      const a = new T.Vector3(...world(points[i - 1])), b = new T.Vector3(...world(points[i]));
      const length = a.distanceTo(b);
      const strip = new T.Mesh(new T.PlaneGeometry(length, 0.12), new T.MeshBasicMaterial({ color, side: T.DoubleSide }));
      strip.rotation.set(-Math.PI / 2, 0, Math.atan2(-(b.z - a.z), b.x - a.x));
      strip.position.copy(a.add(b).multiplyScalar(0.5)); strip.position.y = 0.015; parent.add(strip);
    }
  }
  private arc(x: number, y: number, r: number, start: number, end: number): void {
    this.line(Array.from({ length: 97 }, (_, i) => { const a = start + (end - start) * i / 96; return [x + r * Math.cos(a), y + r * Math.sin(a)]; }));
  }
  private markings(): void {
    this.line([[0, 0], [105, 0], [105, 68], [0, 68], [0, 0]]);
    this.line([[52.5, 0], [52.5, 68]]); this.arc(52.5, 34, 9.15, 0, Math.PI * 2);
    for (const x of [0, 105]) {
      const s = x === 0 ? 1 : -1;
      for (const [depth, width] of [[16.5, 40.32], [5.5, 18.32]]) this.line([[x, 34 - width / 2], [x + s * depth, 34 - width / 2], [x + s * depth, 34 + width / 2], [x, 34 + width / 2]]);
      const angle = Math.acos(5.5 / 9.15);
      this.arc(x + s * 11, 34, 9.15, s === 1 ? -angle : Math.PI - angle, s === 1 ? angle : Math.PI + angle);
      this.arc(x + s * 11, 34, 0.13, 0, 2 * Math.PI);
    }
    this.arc(52.5, 34, 0.13, 0, 2 * Math.PI);
    this.arc(0, 0, 1, 0, Math.PI / 2); this.arc(105, 0, 1, Math.PI / 2, Math.PI);
    this.arc(105, 68, 1, Math.PI, Math.PI * 1.5); this.arc(0, 68, 1, Math.PI * 1.5, Math.PI * 2);
  }
  private goals(): void {
    for (const x of [-52.5, 52.5]) {
      const s = Math.sign(x), back = x + s * 2;
      for (const z of [-3.66, 3.66]) {
        this.box(0.12, 2.44, 0.12, '#ffffff', [x, 1.22, z]);
        this.box(2, 0.08, 0.08, '#cbd7d9', [x + s, 2.44, z]);
      }
      this.box(0.12, 0.12, 7.44, '#ffffff', [x, 2.44, 0]);
      const points: T.Vector3[] = [];
      for (let z = -3.66; z <= 3.67; z += 0.3) {
        points.push(new T.Vector3(back, 0, z), new T.Vector3(back, 2.44, z), new T.Vector3(x, 2.44, z), new T.Vector3(back, 2.44, z));
      }
      for (let h = 0; h <= 2.45; h += 0.3) points.push(new T.Vector3(back, h, -3.66), new T.Vector3(back, h, 3.66));
      this.scene.add(new T.LineSegments(new T.BufferGeometry().setFromPoints(points), new T.LineBasicMaterial({ color: '#d3dedc', transparent: true, opacity: 0.55 })));
    }
  }
  private actor(p: Player): T.Group {
    const group = new T.Group();
    const team = p.team === 'referee' ? undefined : this.info[p.team];
    const roster = team?.players.find(r => r.id === p.id);
    const shirt = roster?.pos === 'GK' ? team?.kit.goalkeeper ?? team?.kit.shirt : team?.kit.shirt;
    const torso = this.box(0.58, 0.65, 0.32, shirt ?? '#ffe45e', [0, 1.15, 0], group);
    torso.name = 'shirt'; torso.castShadow = true;
    const shorts = this.box(0.51, 0.32, 0.3, team?.kit.shorts ?? '#222222', [0, 0.68, 0], group);
    shorts.name = 'shorts'; shorts.castShadow = true;
    for (const side of [-1, 1]) {
      const leg = new T.Group(); leg.name = `leg${side}`; leg.position.set(side * 0.16, 0.545, 0);
      this.box(0.16, 0.53, 0.18, '#e3d6b8', [0, -0.265, 0], leg).castShadow = true;
      const arm = new T.Group(); arm.name = `arm${side}`; arm.position.set(side * 0.38, 1.395, 0);
      this.box(0.16, 0.55, 0.18, shirt ?? '#ffe45e', [0, -0.275, 0], arm).castShadow = true;
      group.add(leg, arm);
    }
    if (roster) {
      // A shirt-surface decal, never a floating tracking label. Created once per actor.
      const canvas = document.createElement('canvas'); canvas.width = 128; canvas.height = 128;
      const context = canvas.getContext('2d')!;
      const color = new T.Color(shirt ?? '#ffe45e');
      const luminance = 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b;
      context.fillStyle = luminance > 0.179 ? '#111111' : '#ffffff';
      context.font = 'bold 88px sans-serif'; context.textAlign = 'center'; context.textBaseline = 'middle';
      context.fillText(String(roster.number), 64, 67);
      const texture = new T.CanvasTexture(canvas); texture.colorSpace = T.SRGBColorSpace;
      const number = new T.Mesh(new T.PlaneGeometry(0.43, 0.43), new T.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false }));
      number.name = 'number'; number.position.set(0, 1.15, -0.163); number.rotation.y = Math.PI;
      number.userData.number = roster.number; number.visible = this.config.jerseyNumbers; group.add(number);
    }
    const head = new T.Mesh(new T.SphereGeometry(0.19, 12, 10), new T.MeshStandardMaterial({ color: '#c99c78' }));
    head.position.y = 1.69; head.castShadow = true; group.add(head);
    group.userData.playerId = p.id; group.userData.team = p.team;
    const richBody = this.richStyle.player(team, p.id, roster?.pos === 'GK');
    const number = group.getObjectByName('number') as T.Mesh | undefined;
    if (number) {
      const decal = number.clone(); decal.name = 'rich-number'; decal.position.set(0, 1.17, -0.205); richBody.add(decal);
    }
    richBody.visible = false; group.add(richBody);
    this.scene.add(group); this.actors.set(p.id, group); return group;
  }
  setRich(enabled: boolean): void {
    this.rich = enabled; this.richStyle.stadium.visible = enabled; this.fill.visible = enabled;
    // Soft local contact cards ground players without a costly full-pitch shadow pass.
    this.renderer.shadowMap.enabled = false;
    this.sky.intensity = enabled ? 1.6 : 2; this.sun.intensity = enabled ? 2.1 : 2.3;
    this.scene.background = new T.Color(enabled ? '#0d1724' : '#243d45');
    this.renderer.toneMapping = enabled ? T.ACESFilmicToneMapping : T.NoToneMapping;
    this.renderer.toneMappingExposure = enabled ? 1.12 : 1;
    this.pitchMeshes.forEach((mesh, i) => { mesh.material = enabled ? this.richStyle.pitch[i % 2] : this.cleanPitchMaterials[i]; });
  }
  /** Scale geometry about tracked anchors, never the scene or input positions. */
  configure(input: Partial<RenderConfig>): RenderConfig {
    this.config = renderConfig({ ...this.config, ...input });
    this.ball.material = this.config.cvVisibility ? this.cvBallMaterial : this.physicalBallMaterial;
    return { ...this.config };
  }
  /** Inspection for automation; contains actual scene transforms, never drawn onto footage. */
  inspect() {
    return {
      config: { ...this.config },
      presentation: { rich: this.rich, crowdInstances: this.rich ? this.richStyle.crowdCount : 0 },
      camera: { position: this.camera.position.toArray(), quaternion: this.camera.quaternion.toArray(), fov: this.camera.fov, zoom: this.camera.zoom },
      ball: {
        position: this.ball.position.toArray(), scale: this.ball.scale.toArray(),
        projectedDiameterPx: projectedDiameter(this.camera, this.ball.position, this.renderer.domElement.height, BALL_RADIUS_M * this.ball.scale.x),
        centerOccludedByPlayer: this.ballOccluded(),
      },
      players: [...this.actors.entries()].filter(([, actor]) => actor.visible).map(([id, actor]) => ({
        id, position: actor.position.toArray(), scale: actor.scale.toArray(), heading: actor.rotation.y,
        stride: actor.getObjectByName(this.rich ? 'rich-leg1' : 'leg1')!.rotation.x,
        jerseyNumber: actor.getObjectByName('number')?.userData.number as number | undefined,
        numberVisible: actor.getObjectByName(this.rich ? 'rich-number' : 'number')?.visible ?? false, team: actor.userData.team as string,
        shirtColor: `#${((actor.getObjectByName(this.rich ? 'rich-shirt' : 'shirt') as T.Mesh).material as T.MeshStandardMaterial).color.getHexString()}`,
        shortsColor: `#${((actor.getObjectByName(this.rich ? 'rich-shorts' : 'shorts') as T.Mesh).material as T.MeshStandardMaterial).color.getHexString()}`,
      })),
    };
  }
  /** Runtime counters are deliberately separate from deterministic scene inspection. */
  statistics() {
    return { drawCalls: this.renderer.info.render.calls, triangles: this.renderer.info.render.triangles,
      geometries: this.renderer.info.memory.geometries, textures: this.renderer.info.memory.textures,
      crowdInstances: this.rich ? this.richStyle.crowdCount : 0 };
  }
  private ballOccluded(): boolean {
    const direction = this.ball.position.clone().sub(this.camera.position);
    const ray = new T.Raycaster(this.camera.position, direction.clone().normalize(), 0, Math.max(0, direction.length() - BALL_RADIUS_M * this.ball.scale.x));
    const targets = [...this.actors.values()].filter(a => a.visible).flatMap(actor => this.rich
      ? actor.getObjectByName('rich-body')!.children.filter(child => child.name !== 'contact-shadow')
      : actor.children.filter(child => child.name !== 'rich-body'));
    return ray.intersectObjects(targets, true).length > 0;
  }
  resize(w: number, h: number): void {
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }
  /** Absolute state application makes seeking/export independent of playback history. */
  render(frame: Frame, target?: T.Vector3, poses?: Map<number, PlayerPose>): void {
    for (const actor of this.actors.values()) actor.visible = false;
    for (const p of frame.players) {
      const actor = this.actors.get(p.id) ?? this.actor(p);
      actor.visible = true; actor.position.set(...world(p.pos)); actor.scale.setScalar(this.config.playerScale);
      const pose = poses?.get(p.id);
      actor.rotation.y = this.config.animatePlayers ? pose?.heading ?? 0 : 0;
      const stride = this.config.animatePlayers ? pose?.stride ?? 0 : 0;
      for (const side of [-1, 1]) {
        actor.getObjectByName(`leg${side}`)!.rotation.x = side * stride;
        actor.getObjectByName(`arm${side}`)!.rotation.x = -side * stride * 0.65;
      }
      for (const child of actor.children) child.visible = child.name === 'rich-body' ? this.rich : !this.rich;
      const number = actor.getObjectByName('number'); if (number) number.visible = !this.rich && this.config.jerseyNumbers;
      const richNumber = actor.getObjectByName('rich-number'); if (richNumber) richNumber.visible = this.config.jerseyNumbers;
      const swing = this.config.animatePlayers ? richGait(frame.t, p.id, pose?.speed ?? 0) : 0;
      for (const side of [-1, 1]) {
        actor.getObjectByName(`rich-leg${side}`)!.rotation.x = side * swing;
        actor.getObjectByName(`rich-knee${side}`)!.rotation.x = Math.max(0, -side * swing) * 0.65;
        actor.getObjectByName(`rich-arm${side}`)!.rotation.x = -side * swing * 0.7 - 0.12;
      }
    }
    this.ball.position.set(...world(frame.ball));
    applyCamera(this.camera, this.config.camera, target ?? this.ball.position);
    const diameter = projectedDiameter(this.camera, this.ball.position, this.renderer.domElement.height);
    this.ball.scale.setScalar(ballScale(this.config, diameter));
    this.renderer.render(this.scene, this.camera);
  }
  dispose(): void {
    const geometries = new Set<T.BufferGeometry>(this.richStyle.geometries.values());
    const materials = new Set<T.Material>([...this.richStyle.materials.values(), ...this.richStyle.pitch, this.richStyle.shadowMaterial, ...this.cleanPitchMaterials, this.physicalBallMaterial, this.cvBallMaterial]);
    const textures = new Set<T.Texture>(this.richStyle.textures);
    this.scene.traverse(o => {
      if (o instanceof T.InstancedMesh) o.dispose();
      if (o instanceof T.Mesh || o instanceof T.LineSegments) {
        geometries.add(o.geometry);
        for (const material of Array.isArray(o.material) ? o.material : [o.material]) materials.add(material);
      }
    });
    for (const material of materials) { if ('map' in material && material.map) textures.add(material.map as T.Texture); material.dispose(); }
    for (const geometry of geometries) geometry.dispose();
    for (const texture of textures) texture.dispose();
    this.sun.shadow.dispose(); this.renderer.dispose();
  }
}
