import * as T from 'three';
import type { Team } from '../data/match';

/** Speed blends two timestamp-driven gaits; changing speed never multiplies a large match clock. */
export function richGait(t: number, id: number, speed: number): number {
  const blend = T.MathUtils.smoothstep(speed, 1, 4);
  const phase = id * 0.7;
  const cycle = T.MathUtils.lerp(Math.sin(t * Math.PI * 2 + phase), Math.sin(t * Math.PI * 3.7 + phase), blend);
  return speed > 0.15 ? cycle * Math.min(0.58, speed * 0.13) : 0;
}

/** Procedural rich-only assets. Shared geometry/materials keep the stadium inexpensive. */
export class RichStyle {
  readonly stadium = new T.Group();
  readonly materials = new Map<string, T.MeshStandardMaterial>();
  readonly geometries = new Map<string, T.BufferGeometry>();
  readonly textures: T.Texture[] = [];
  readonly pitch: T.MeshStandardMaterial[];
  readonly crowdCount: number;
  readonly shadowMaterial: T.MeshBasicMaterial;
  constructor() {
    // Broad mowing colors avoid high-frequency texture noise that dominates PNG capture time.
    this.pitch = ['#4d9558', '#43864e'].map(color => new T.MeshStandardMaterial({ color, roughness: 1 }));
    const shadow = this.canvas(64, 64, ctx => {
      const gradient = ctx.createRadialGradient(32, 32, 2, 32, 32, 31);
      gradient.addColorStop(0, 'rgba(8,18,17,.38)'); gradient.addColorStop(1, 'rgba(8,18,17,0)');
      ctx.fillStyle = gradient; ctx.fillRect(0, 0, 64, 64);
    });
    this.shadowMaterial = new T.MeshBasicMaterial({ map: shadow, transparent: true, depthWrite: false });
    this.crowdCount = this.environment();
  }
  private canvas(width: number, height: number, draw: (ctx: CanvasRenderingContext2D) => void): T.CanvasTexture {
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
    draw(canvas.getContext('2d')!);
    const texture = new T.CanvasTexture(canvas); texture.colorSpace = T.SRGBColorSpace; this.textures.push(texture);
    return texture;
  }
  private geometry(key: string, create: () => T.BufferGeometry): T.BufferGeometry {
    if (!this.geometries.has(key)) this.geometries.set(key, create());
    return this.geometries.get(key)!;
  }
  private material(color: string): T.MeshStandardMaterial {
    if (!this.materials.has(color)) this.materials.set(color, new T.MeshStandardMaterial({ color, roughness: 0.88 }));
    return this.materials.get(color)!;
  }
  private box(parent: T.Object3D, color: string, size: number[], position: number[]): T.Mesh {
    const mesh = new T.Mesh(this.geometry('box', () => new T.BoxGeometry()), this.material(color));
    mesh.scale.set(...size as [number, number, number]); mesh.position.set(...position as [number, number, number]); parent.add(mesh); return mesh;
  }
  private cylinder(parent: T.Object3D, color: string, radius: number, height: number, position: number[]): T.Mesh {
    const mesh = new T.Mesh(this.geometry('cylinder', () => new T.CylinderGeometry(1, 1, 1, 8)), this.material(color));
    mesh.scale.set(radius, height, radius); mesh.position.set(...position as [number, number, number]); mesh.castShadow = true; parent.add(mesh); return mesh;
  }
  private environment(): number {
    const seats: T.Vector3[] = [], people: T.Vector3[] = [];
    const palette = ['#224861', '#2e6078', '#bf554e', '#d5b890', '#abb7be', '#333d50'];
    for (const side of [-1, 1]) {
      for (let row = 0; row < 12; row++) {
        const height = 0.8 + row * 0.65, distance = 40 + row * 1.15;
        this.box(this.stadium, row % 3 ? '#344454' : '#405464', [124, 0.65, 1.2], [0, height - 0.3, side * distance]);
        this.box(this.stadium, row % 3 ? '#344454' : '#405464', [1.2, 0.65, 76], [side * (57 + row * 1.15), height - 0.3, 0]);
        for (let i = 0; i < 100; i++) seats.push(new T.Vector3((i - 49.5) * 1.2, height, side * distance));
        for (let i = 0; i < 60; i++) seats.push(new T.Vector3(side * (57 + row * 1.15), height, (i - 29.5) * 1.2));
      }
      this.box(this.stadium, '#182a38', [128, 0.35, 5], [0, 9.6, side * 52]);
      this.box(this.stadium, '#182a38', [5, 0.35, 78], [side * 69, 9.6, 0]);
      this.box(this.stadium, '#667b83', [124, 0.9, 0.25], [0, 0.45, side * 38.5]);
      this.box(this.stadium, '#667b83', [0.25, 0.9, 74], [side * 55.5, 0.45, 0]);
      for (let x = -60; x <= 60; x += 20) this.box(this.stadium, '#a4b3b9', [0.15, 9, 0.15], [x, 4.7, side * 53.5]);
    }
    const benches = seats.filter((_, i) => i % 4 === 0);
    const seatMesh = new T.InstancedMesh(this.geometry('seat', () => new T.BoxGeometry(4.55, 0.14, 0.65)), this.material('#ffffff'), benches.length);
    const dummy = new T.Object3D();
    benches.forEach((position, i) => {
      dummy.position.copy(position); dummy.position.x += Math.abs(position.z) < 38 ? 0 : 1.8;
      if (Math.abs(position.z) < 38) { dummy.position.z += 1.8; dummy.rotation.y = Math.PI / 2; } else dummy.rotation.y = 0;
      dummy.updateMatrix(); seatMesh.setMatrixAt(i, dummy.matrix);
      seatMesh.setColorAt(i, new T.Color(palette[Math.floor(i / 5) % palette.length]));
    });
    seats.forEach((position, i) => {
      if ((i * 31 % 17) > 2) { people.push(position.clone().add(new T.Vector3(0, 0.50, 0))); }
    });
    this.stadium.add(seatMesh);
    // Four instanced cutout batches replace thousands of tiny head/torso meshes.
    // Each spectator uses two triangles, with fixed stand-facing orientation and no animation.
    const crowdColors = ['#2c6680', '#c45d53', '#d9c4a2', '#b1c0c8'];
    for (let batch = 0; batch < crowdColors.length; batch++) {
      const texture = this.canvas(64, 96, ctx => {
        ctx.fillStyle = '#c79b7c'; ctx.beginPath(); ctx.arc(32, 14, 10, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = crowdColors[batch]; ctx.beginPath(); ctx.moveTo(18, 26); ctx.lineTo(46, 26); ctx.lineTo(57, 63); ctx.lineTo(8, 63); ctx.closePath(); ctx.fill();
        ctx.fillStyle = '#293747'; ctx.fillRect(19, 62, 11, 28); ctx.fillRect(34, 62, 11, 28);
      });
      const entries = people.filter((_, i) => i % crowdColors.length === batch);
      const material = new T.MeshBasicMaterial({ map: texture, alphaTest: 0.5, side: T.DoubleSide });
      const crowd = new T.InstancedMesh(this.geometry('crowd-card', () => new T.PlaneGeometry(0.65, 1)), material, entries.length);
      entries.forEach((position, i) => {
        dummy.position.copy(position); dummy.rotation.y = Math.abs(position.z) < 38 ? Math.PI / 2 : 0;
        dummy.updateMatrix(); crowd.setMatrixAt(i, dummy.matrix);
      });
      this.stadium.add(crowd);
    }
    // Four floodlight structures; emissive lamp panels, not dozens of extra shadow lights.
    for (const x of [-62, 62]) for (const z of [-38, 38]) {
      this.box(this.stadium, '#788b98', [0.35, 19, 0.35], [x, 9.5, z]);
      this.box(this.stadium, '#263b4a', [4.8, 2, 0.4], [x, 19, z]);
      const lamp = new T.MeshBasicMaterial({ color: '#f3f8ff' });
      for (let i = 0; i < 8; i++) {
        const panel = new T.Mesh(this.geometry('lamp', () => new T.BoxGeometry(0.8, 0.65, 0.48)), lamp);
        panel.position.set(x - 1.65 + i % 4 * 1.1, 18.55 + Math.floor(i / 4) * 0.9, z); this.stadium.add(panel);
      }
    }
    const slogans = ['INSIDE THE GAME', 'SYNTHETIC FOOTBALL', 'PLAY. SEE. UNDERSTAND.'];
    const boards = slogans.map((label, i) => new T.MeshBasicMaterial({ map: this.canvas(512, 64, ctx => {
      ctx.fillStyle = ['#15374b', '#dfbb75', '#c5dbd5'][i]; ctx.fillRect(0, 0, 512, 64);
      ctx.fillStyle = i ? '#173543' : '#f0e5cd'; ctx.font = 'bold 28px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, 256, 33);
    }) }));
    for (const side of [-1, 1]) for (let i = 0; i < 10; i++) {
      const board = new T.Mesh(this.geometry('board', () => new T.PlaneGeometry(9.7, 0.9)), boards[i % boards.length]);
      board.position.set((i - 4.5) * 10.1, 0.55, side * 37); board.rotation.y = side < 0 ? 0 : Math.PI; this.stadium.add(board);
    }
    return people.length;
  }
  /** Rich body lives under the same unmodified root anchor as the clean model. */
  player(team: Team | undefined, id: number, goalkeeper: boolean): T.Group {
    const group = new T.Group(); group.name = 'rich-body';
    const shirt = (goalkeeper ? team?.kit.goalkeeper ?? team?.kit.shirt : team?.kit.shirt) ?? '#ffe45e';
    const shorts = team?.kit.shorts ?? '#222222';
    const skin = ['#bd8e6b', '#e0b591', '#8a5b42', '#694530'][id % 4];
    const torso = new T.Mesh(this.geometry('torso', () => new T.CylinderGeometry(0.31, 0.245, 0.62, 8)), this.material(shirt));
    torso.name = 'rich-shirt'; torso.scale.z = 0.65; torso.position.y = 1.17; torso.castShadow = true; group.add(torso);
    const pants = this.box(group, shorts, [0.47, 0.29, 0.30], [0, 0.76, 0]); pants.name = 'rich-shorts'; pants.castShadow = true;
    this.cylinder(group, skin, 0.075, 0.13, [0, 1.51, 0]);
    const head = new T.Mesh(this.geometry('head', () => new T.SphereGeometry(0.175, 12, 10)), this.material(skin));
    head.position.y = 1.72; head.scale.y = 1.1; head.castShadow = true; group.add(head);
    const hair = new T.Mesh(this.geometry('hair', () => new T.SphereGeometry(0.178, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2)), this.material(id % 3 ? '#302b28' : '#79583e'));
    hair.position.y = 1.76; hair.scale.y = 0.8; group.add(hair);
    for (const side of [-1, 1]) {
      const leg = new T.Group(); leg.name = `rich-leg${side}`; leg.position.set(side * 0.135, 0.66, 0);
      this.cylinder(leg, shorts, 0.115, 0.20, [0, -0.05, 0]);
      this.cylinder(leg, skin, 0.085, 0.16, [0, -0.22, 0]);
      const knee = new T.Group(); knee.name = `rich-knee${side}`; knee.position.y = -0.29;
      this.cylinder(knee, shorts, 0.075, 0.27, [0, -0.14, 0]);
      this.cylinder(knee, '#e7e9e4', 0.078, 0.055, [0, -0.025, 0]);
      const boot = this.box(knee, '#202832', [0.17, 0.09, 0.27], [0, -0.325, 0.045]); boot.castShadow = true;
      leg.add(knee); group.add(leg);
      const arm = new T.Group(); arm.name = `rich-arm${side}`; arm.position.set(side * 0.31, 1.4, 0); arm.rotation.z = side * 0.12;
      this.cylinder(arm, shirt, 0.10, 0.22, [side * 0.02, -0.10, 0]);
      this.cylinder(arm, skin, 0.07, 0.23, [side * 0.035, -0.31, 0.025]); group.add(arm);
    }
    const shadow = new T.Mesh(this.geometry('contact', () => new T.PlaneGeometry(1.1, 0.8)), this.shadowMaterial);
    shadow.name = 'contact-shadow'; shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.035; group.add(shadow);
    return group;
  }
}
