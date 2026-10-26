import * as T from 'three';
import { world, type Frame, type MatchInfo, type Player } from '../data/match';
import { applyCamera } from '../camera/presets';
import { BALL_RADIUS_M, renderConfig, type RenderConfig } from './config';
import { createBall, projectedDiameter, ballScale } from './ball';

/** Fixed world geometry: no random values or wall-clock-dependent animation. */
export class Broadcast {
  readonly renderer: T.WebGLRenderer;
  readonly scene = new T.Scene();
  readonly camera = new T.PerspectiveCamera(43, 16 / 9, 0.1, 400);
  private actors = new Map<number, T.Group>();
  private stadium = new T.Group();
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
    this.scene.add(new T.HemisphereLight(0xe9f6ff, 0x486332, 2));
    this.sun.position.set(-30, 65, 30); this.sun.castShadow = true;
    Object.assign(this.sun.shadow.camera, { left: -75, right: 75, top: 65, bottom: -65, far: 180 });
    this.sun.shadow.mapSize.set(2048, 2048); this.sun.shadow.bias = -0.0003;
    this.scene.add(this.sun);
    this.box(140, 0.2, 100, '#233b31', [0, -0.16, 0]);
    for (let i = 0; i < 14; i++) this.box(7.5, 0.05, 68, i % 2 ? '#398b49' : '#348044', [-48.75 + i * 7.5, -0.025, 0]).receiveShadow = true;
    this.markings(); this.goals(); this.environment();
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
  private environment(): void {
    for (let tier = 0; tier < 6; tier++) {
      for (const s of [-1, 1]) {
        this.box(135, 1.5, 2.8, tier % 2 ? '#435b6a' : '#526c7b', [0, 1 + tier * 1.5, s * (43 + tier * 2.8)], this.stadium);
        this.box(2.8, 1.5, 84, '#435b6a', [s * (62 + tier * 2.8), 1 + tier * 1.5, 0], this.stadium);
      }
    }
    this.scene.add(this.stadium);
  }
  private actor(p: Player): T.Group {
    const group = new T.Group();
    const team = p.team === 'referee' ? undefined : this.info[p.team];
    const roster = team?.players.find(r => r.id === p.id);
    const shirt = roster?.pos === 'GK' ? team?.kit.goalkeeper ?? team?.kit.shirt : team?.kit.shirt;
    this.box(0.58, 0.65, 0.32, shirt ?? '#ffe45e', [0, 1.15, 0], group).castShadow = true;
    this.box(0.51, 0.32, 0.3, team?.kit.shorts ?? '#222222', [0, 0.68, 0], group).castShadow = true;
    for (const s of [-1, 1]) {
      this.box(0.16, 0.53, 0.18, '#e3d6b8', [s * 0.16, 0.28, 0], group).castShadow = true;
      this.box(0.16, 0.55, 0.18, shirt ?? '#ffe45e', [s * 0.38, 1.12, 0], group).castShadow = true;
    }
    const head = new T.Mesh(new T.SphereGeometry(0.19, 12, 10), new T.MeshStandardMaterial({ color: '#c99c78' }));
    head.position.y = 1.69; head.castShadow = true; group.add(head);
    group.userData.playerId = p.id; group.userData.team = p.team;
    this.scene.add(group); this.actors.set(p.id, group); return group;
  }
  setRich(enabled: boolean): void { this.stadium.visible = enabled; this.renderer.shadowMap.enabled = enabled; }
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
      camera: { position: this.camera.position.toArray(), quaternion: this.camera.quaternion.toArray(), fov: this.camera.fov, zoom: this.camera.zoom },
      ball: {
        position: this.ball.position.toArray(), scale: this.ball.scale.toArray(),
        projectedDiameterPx: projectedDiameter(this.camera, this.ball.position, this.renderer.domElement.height, BALL_RADIUS_M * this.ball.scale.x),
        centerOccludedByPlayer: this.ballOccluded(),
      },
      players: [...this.actors.entries()].filter(([, actor]) => actor.visible).map(([id, actor]) => ({
        id, position: actor.position.toArray(), scale: actor.scale.toArray(), team: actor.userData.team as string,
        shirtColor: `#${((actor.children[0] as T.Mesh).material as T.MeshStandardMaterial).color.getHexString()}`,
        shortsColor: `#${((actor.children[1] as T.Mesh).material as T.MeshStandardMaterial).color.getHexString()}`,
      })),
    };
  }
  private ballOccluded(): boolean {
    const direction = this.ball.position.clone().sub(this.camera.position);
    const ray = new T.Raycaster(this.camera.position, direction.clone().normalize(), 0, Math.max(0, direction.length() - BALL_RADIUS_M * this.ball.scale.x));
    return ray.intersectObjects([...this.actors.values()].filter(a => a.visible), true).length > 0;
  }
  resize(w: number, h: number): void {
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }
  /** Absolute state application makes seeking/export independent of playback history. */
  render(frame: Frame, target?: T.Vector3): void {
    for (const actor of this.actors.values()) actor.visible = false;
    for (const p of frame.players) { const actor = this.actors.get(p.id) ?? this.actor(p); actor.visible = true; actor.position.set(...world(p.pos)); actor.scale.setScalar(this.config.playerScale); }
    this.ball.position.set(...world(frame.ball));
    applyCamera(this.camera, this.config.camera, target ?? this.ball.position);
    const diameter = projectedDiameter(this.camera, this.ball.position, this.renderer.domElement.height);
    this.ball.scale.setScalar(ballScale(this.config, diameter));
    this.renderer.render(this.scene, this.camera);
  }
  dispose(): void {
    this.scene.traverse(o => { if (o instanceof T.Mesh || o instanceof T.LineSegments) { o.geometry.dispose(); for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose(); } });
    this.sun.shadow.dispose();
    this.physicalBallMaterial.dispose(); this.cvBallMaterial.dispose();
    this.renderer.dispose();
  }
}
